import logging

from django.utils.translation import gettext_lazy as _

from publication.api.publication import PublicationAPI
from publication.utils.journal import build_journal


def publish_journal(user, website, scielo_journal):
    try:
        payload = {}
        build_journal(scielo_journal, JournalPayload(payload))

        api = PublicationAPI(
            post_data_url=website.api_url_journal,
            get_token_url=website.api_get_token_url,
            username=website.api_username or user.username,
            password=website.api_password or user.password,
            timeout=website.api_timeout,
        )
        response = api.post_data(payload)
        if response.get("result") == "OK":
            scielo_journal.update_publication_stage()
            scielo_journal.save()

    except Exception as e:
        logging.exception(e)
        # TODO registrar exceção no falhas de publicação


class JournalPayload:
    def __init__(self, data=None):
        self.data = data or {}
        self.reset_lists()

    def reset_lists(self):
        self.data["sponsors"] = []
        self.data["timeline"] = []
        self.data["mission"] = []

    def add_ids(self, journal_id):
        self.data["jid"] = journal_id
        self.data["_id"] = journal_id

    def add_acron(self, acron):
        self.data["acronym"] = acron

    def add_journal_titles(self, title, title_iso, short_title):
        self.data["title"] = title
        self.data["title_iso"] = title_iso
        self.data["short_title"] = short_title

    def add_journal_issns(self, scielo_issn, eletronic_issn, print_issn=None):
        self.data["scielo_issn"] = scielo_issn
        self.data["print_issn"] = print_issn
        self.data["eletronic_issn"] = eletronic_issn

    def add_thematic_scopes(self, subject_categories, subject_areas):
        # Subject Categories
        self.data["subject_categories"] = subject_categories

        # Study Area
        self.data["study_areas"] = subject_areas

    def add_issue_count(self, issue_count):
        # Issue count
        self.data["issue_count"] = issue_count

    def add_sponsor(self, sponsor):
        # Sponsors
        if not self.data["sponsors"]:
            self.data["sponsors"] = []
        self.data["sponsors"].append(sponsor)

    def add_contact(self, name, email, address, city, state, country):
        # email to contact
        self.data["editor_email"] = email
        self.data["publisher_address"] = address
        self.data["publisher_name"] = name
        self.data["publisher_city"] = city
        self.data["publisher_state"] = state
        self.data["publisher_country"] = country

    def add_logo_url(self, logo_url):
        self.data["logo_url"] = logo_url

    def add_online_submission_url(self, online_submission_url):
        self.data["online_submission_url"] = online_submission_url

    def add_related_journals(self, previous_journal, next_journal_title):
        self.data["next_title"] = next_journal_title
        self.data["previous_journal_ref"] = previous_journal

    def add_event_to_timeline(self, status, since, reason):
        """
        Add item to self.data["timeline

        Parameters
        ----------
        status : StringField
        since : DateTimeField
        reason : StringField

        """
        if status and since:
            if not self.data["timeline"]:
                self.data["timeline"] = []

            self.data["timeline"].append(
                {
                    "status": status or "",
                    "since": since or "",
                    "reason": reason or "",
                }
            )
            self.data["current_status"] = self.data["timeline"][-1].status

    def add_mission(self, language, description):
        """
        Add item to self.data["mission

        Parameters
        ----------
        language : StringField
        description : StringField

        """
        if language and description:
            if not self.data["mission"]:
                self.data["mission"] = []

            self.data["mission"].append(
                {
                    "language": language or "",
                    "description": description or "",
                }
            )

    def add_metrics(self, total_h5_index, total_h5_median, h5_metric_year):
        """
        Add item to self.data["metrics

        Parameters
        ----------

        total_h5_index : IntField
        total_h5_median : IntField
        h5_metric_year : IntField

        """
        if all([total_h5_index, total_h5_median, h5_metric_year]):
            self.data["metrics"] = {
                "total_h5_index": total_h5_index or None,
                "total_h5_median": total_h5_median or None,
                "h5_metric_year": h5_metric_year or None,
            }

    def add_is_public(self):
        self.data["is_public"] = True
