from opac_schema.v1.models import (
    Issue,
    Journal,
)
from . import exceptions
from . import db


def get_issue(issue_id):
    """
    Get registered issue or new issue

    Parameters
    ----------
    issue_id : str

    Returns
    -------
    Issue
    """
    try:
        issue = Issue.objects.get(_id=issue_id)
    except Issue.DoesNotExist:
        issue = Issue()
        issue._id = issue_id
    return issue


def _set_issue_type(issue):

    if issue.suppl_text:
        issue.type = "supplement"
        return

    if issue.volume and not issue.number:
        issue.type = "volume_issue"

    if issue.number == "ahead":
        issue.type == "ahead"
        issue.year = "9999"
        return

    if issue.number and "spe" in issue.number:
        issue.type = "special"
        return


class IssueToPublish:
    def __init__(self, issue_id):
        self.issue = get_issue(issue_id)
        self._has_docs = None

    def add_journal(self, journal):
        if isinstance(journal, Journal):
            self.issue.journal = journal
        else:
            self.issue.journal = Journal.objects.get(_id=journal)

    def add_order(self, order):
        self.issue.order = order

    def add_pid(self, pid):
        self.issue.pid = pid

    def add_publication_date(self, year, start_month, end_month):
        self.issue.start_month = start_month
        self.issue.end_month = end_month
        self.issue.year = year

    def add_identification(self, volume, number, supplement):
        self.issue.volume = volume
        self.issue.suppl_text = supplement
        if "spe" in number:
            self.issue.spe_text = number
        else:
            self.issue.number = number

        # set label
        prefixes = ("v", "n", "s")
        values = (volume, number, supplement)
        self.issue.label = "".join(
            f"{prefix}{value}"
            for prefix, value in zip(prefixes, values)
            if value
        )
        # set issue type
        _set_issue_type(self.issue)

    @property
    def has_docs(self):
        return self._has_docs

    @has_docs.setter
    def has_docs(self, documents):
        self._has_docs = documents

    def publish_issue(self):
        """
        Publishes issue data

        Raises
        ------
        IssueSaveError

        Returns
        -------
        opac_schema.v1.models.Issue
        """

        try:
            if self.issue.type == "ahead" and not self.has_docs:
                """
                Caso não haja nenhum artigo no bundle de ahead, ele é definido como
                ``outdated_ahead``, para que não apareça na grade de fascículos
                """
                self.issue.type = "outdated_ahead"

        except KeyError as e:
            raise exceptions.IssueDataError(e)

        try:
            db.save_data(self.issue)
        except Exception as e:
            raise exceptions.IssueSaveError(e)

        return issue
