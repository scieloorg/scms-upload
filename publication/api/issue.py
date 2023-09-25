from django.utils.translation import gettext_lazy as _

from publication.utils.issue import get_bundle_id


def publish_issue(user, website, scielo_issue):
    try:
        data = {}
        builder = IssuePayload(data)
        build_issue(scielo_issue, journal_id, builder)
        api = PublicationAPI(
            post_data_url=website.api_url_issue,
            get_token_url=website.api_get_token_url,
            username=website.api_username or user.username,
            password=website.api_password or user.password,
            timeout=website.api_timeout,
        )
        response = api.post_data(data)
        if response.get("result") == "OK":
            scielo_issue.update_publication_stage()
            scielo_issue.save()

    except Exception as e:
        logging.exception(e)
        # TODO registrar exceção no falhas de publicação


class IssuePayload:
    def __init__(self, data=None):
        self.data = data or {}
        self._has_docs = None

    def add_ids(self, issue_id):
        self.data["_id"] = issue_id
        self.data["iid"] = issue_id

    def add_order(self, order):
        self.data["order"] = order

    def add_pid(self, pid):
        self.data["pid"] = pid

    def add_publication_date(self, year, start_month, end_month):
        # nao está sendo usado
        # self.data["start_month"] = start_month
        # self.data["end_month"] = end_month
        self.data["year"] = str(year)

    def add_identification(self, volume, number, supplement):
        self.data["volume"] = volume
        self.data["suppl_text"] = supplement
        if number:
            if "spe" in number:
                self.data["spe_text"] = number
            else:
                self.data["number"] = number

        # set label
        prefixes = ("v", "n", "s")
        values = (volume, number, supplement)
        self.data["label"] = "".join(
            f"{prefix}{value}" for prefix, value in zip(prefixes, values) if value
        )
        # set issue type
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
        if self.data["suppl_text"]:
            self.data["type"] = "supplement"
            return

        if self.data["volume"] and not self.data["number"]:
            self.data["type"] = "volume_self.data"
            return

        if self.data["number"] == "ahead":
            self.data["type"] == "ahead"
            self.data["year"] = "9999"
            return

        if self.data["number"] and "spe" in self.data["number"]:
            self.data["type"] = "special"
            return

        self.data["type"] = "regular"

    def add_journal(self, journal_id):
        self.data["journal"] = journal_id
