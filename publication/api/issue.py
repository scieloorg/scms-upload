import logging

from django.utils.translation import gettext_lazy as _

from publication.api.publication import PublicationAPI
from publication.utils.issue import build_issue


def publish_issue(issue_proc, api_data):
    issue = issue_proc.issue
    issue_id = issue_proc.pid
    journal_id = issue_proc.journal_proc.pid

    data = {}
    builder = IssuePayload(data)
    build_issue(builder, journal_id, issue, issue_id)
    api = PublicationAPI(**api_data)
    response = api.post_data(data, {"journal_id": journal_id})
    response["payload"] = data
    return response


class IssuePayload:
    """
    {
        "publication_year": "1998",
        "volume": "29",
        "number": "3",
        "publication_months": {
            "range": [
                9,
                9
            ]
        },
        "pid": "1678-446419980003",
        "id": "1678-4464-1998-v29-n3",
        "created": "1998-09-01T00:00:00.000000Z",
        "updated": "2020-04-28T20:16:24.459467Z"
    }
    """

    def __init__(self, data=None):
        self.data = data
        self._has_docs = None

    def add_dates(self, created, updated):
        self.data["created"] = created.isoformat()
        if updated:
            self.data["updated"] = updated.isoformat()

    def add_ids(self, issue_id):
        # "1678-4464-1998-v29-n3"
        self.data["id"] = issue_id
        # self.data["iid"] = issue_id

    def add_order(self, order):
        self.data["order"] = order

    def add_pid(self, pid):
        # "1678-446419980003"
        self.data["pid"] = pid

    def add_publication_date(self, year, start_month, end_month):
        # nao está sendo usado
        # self.data["start_month"] = start_month
        # self.data["end_month"] = end_month
        self.data["publication_year"] = str(year)
        if start_month or end_month:
            try:
                start_month = int(start_month or end_month)
                end_month = int(end_month or start_month)
                self.data["publication_months"] = {"range": [start_month, end_month]}
            except (TypeError, ValueError):
                pass

    def add_identification(self, volume, number, supplement):
        if volume:
            self.data["volume"] = volume
        if supplement is not None:
            self.data["supplement"] = supplement
        if number:
            if "spe" in number:
                self.data["spe_text"] = number
            else:
                self.data["number"] = number

        self.add_issue_type()

    @property
    def has_docs(self):
        return self._has_docs

    @has_docs.setter
    def has_docs(self, documents):
        self._has_docs = documents

    def identify_outdated_ahead(self):
        if self.data["type"] == "ahead" and not self.has_docs:
            """
            Caso não haja nenhum artigo no bundle de ahead, ele é definido como
            ``outdated_ahead``, para que não apareça na grade de fascículos
            """
            self.data["type"] = "outdated_ahead"

    def add_issue_type(self):
        if self.data.get("supplement"):
            self.data["type"] = "supplement"
            return

        if self.data.get("volume") and not self.data.get("number"):
            self.data["type"] = "volume_issue"
            return

        if self.data.get("number") == "ahead":
            self.data["type"] = "ahead"
            self.data["publication_year"] = "9999"
            return

        if self.data.get("number") and "spe" in self.data["number"]:
            self.data["type"] = "special"
            return

        self.data["type"] = "regular"

    def add_journal(self, journal_id):
        self.data["journal_id"] = journal_id
