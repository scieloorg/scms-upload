import logging

from opac_schema.v1.models import Issue as OpacIssue
from opac_schema.v1.models import Journal as OpacJournal

from publication.db import exceptions
from publication.db.db import Publication
from publication.utils.issue import get_bundle_id, build_issue


def publish_issue(user, website, scielo_issue):
    if not website:
        raise ValueError(
            "publication.db.issue.publish_issue requires website parameter"
        )
    if not website.enabled:
        raise ValueError(f"Website {website} status is not enabled")
    if not website.db_uri:
        raise ValueError(
            "publication.db.issue.publish_issue requires website.db_uri parameter"
        )
    if not scielo_issue:
        raise ValueError(
            "publication.db.issue.publish_issue requires scielo_issue parameter"
        )

    publication = IssuePublication(website)
    publication.publish(scielo_issue)


class IssuePublication(Publication):
    def __init__(self, website):
        super().__init__(website, OpacIssue)

    def publish(self, scielo_issue):
        issue = scielo_issue.issue
        year = issue.publication_year
        volume = issue.volume
        number = issue.number
        supplement = issue.supplement

        issue_id = get_bundle_id(
            issn_id=scielo_issue.scielo_journal.scielo_issn,
            year=year,
            volume=volume,
            number=number,
            supplement=supplement,
        )

        obj = self.get_object(_id=issue_id)

        builder = IssueFactory(obj, issue_id)
        build_issue(scielo_issue, scielo_issue.scielo_journal.scielo_issn, builder)
        self.save_object(obj)

        scielo_issue.update_publication_stage()


class IssueFactory:
    def __init__(self, issue):
        self.issue = issue

        self._has_docs = None

    def add_ids(self, issue_id):
        self.issue._id = issue_id
        self.issue.iid = issue_id

    def add_order(self, order):
        self.issue.order = order

    def add_pid(self, pid):
        self.issue.pid = pid

    def add_publication_date(self, year, start_month, end_month):
        # nao está sendo usado
        # self.issue.start_month = start_month
        # self.issue.end_month = end_month
        self.issue.year = str(year)

    def add_identification(self, volume, number, supplement):
        self.issue.volume = volume
        self.issue.suppl_text = supplement
        if number:
            if "spe" in number:
                self.issue.spe_text = number
            else:
                self.issue.number = number

        # set label
        prefixes = ("v", "n", "s")
        values = (volume, number, supplement)
        self.issue.label = "".join(
            f"{prefix}{value}" for prefix, value in zip(prefixes, values) if value
        )
        # set issue type
        _set_issue_type(self.issue)

    @property
    def has_docs(self):
        return self._has_docs

    @has_docs.setter
    def has_docs(self, documents):
        self._has_docs = documents

    def identify_outdated_ahead(self):
        if self.issue.type == "ahead" and not self.has_docs:
            """
            Caso não haja nenhum artigo no bundle de ahead, ele é definido como
            ``outdated_ahead``, para que não apareça na grade de fascículos
            """
            self.issue.type = "outdated_ahead"

    def add_issue_type(self):
        if self.issue.suppl_text:
            self.issue.type = "supplement"
            return

        if self.issue.volume and not self.issue.number:
            self.issue.type = "volume_issue"
            return

        if self.issue.number == "ahead":
            self.issue.type == "ahead"
            self.issue.year = "9999"
            return

        if self.issue.number and "spe" in self.issue.number:
            self.issue.type = "special"
            return

        self.issue.type = "regular"

    def add_journal(self, journal_id):
        self.issue.journal = OpacJournal.objects.get(pk=journal_id)
