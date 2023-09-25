import logging

from opac_schema.v1.models import JounalMetrics, Mission, Timeline
from opac_schema.v1.models import Journal as OpacJournal

from journal.models import Journal
from migration.models import MigratedJournal
from scielo_classic_website.models.journal import Journal as ClassicJournal
from publication.db.db import Publication
from publication.utils.journal import build_journal


def publish_journal(user, website, scielo_journal):
    if not website:
        raise ValueError(
            "publication.db.issue.publish_journal requires website parameter"
        )
    if not website.enabled:
        raise ValueError(f"Website {website} status is not enabled")
    if not website.db_uri:
        raise ValueError(
            "publication.db.journal.publish_journal requires website.db_uri parameter"
        )
    if not scielo_journal:
        raise ValueError(
            "publication.db.journal.publish_journal requires scielo_journal parameter"
        )
    logging.info(f"journal publication {scielo_journal}")
    publication = JournalPublication(website)
    publication.publish(scielo_journal)
    logging.info(f"journal publication {scielo_journal} done")


class JournalPublication(Publication):
    def __init__(self, website):
        super().__init__(website, OpacJournal)

    def publish(self, scielo_journal):
        journal_id = scielo_journal.scielo_issn
        obj = self.get_object(_id=journal_id)
        build_journal(scielo_journal, JournalFactory(obj))
        self.save_object(obj)
        scielo_journal.update_publication_stage()
        scielo_journal.save()


class JournalFactory:
    def __init__(self, journal):
        self.journal = journal
        self.reset_lists()

    def reset_lists(self):
        self.journal.sponsors = []
        self.journal.timeline = []
        self.journal.mission = []

    def add_ids(self, journal_id):
        self.journal.jid = journal_id
        self.journal._id = journal_id

    def add_acron(self, acron):
        self.journal.acronym = acron

    def add_journal_titles(self, title, title_iso, short_title):
        self.journal.title = title
        self.journal.title_iso = title_iso
        self.journal.short_title = short_title

    def add_journal_issns(self, scielo_issn, eletronic_issn, print_issn=None):
        self.journal.scielo_issn = scielo_issn
        self.journal.print_issn = print_issn
        self.journal.eletronic_issn = eletronic_issn

    def add_thematic_scopes(self, subject_categories, subject_areas):
        # Subject Categories
        self.journal.subject_categories = subject_categories

        # Study Area
        self.journal.study_areas = subject_areas

    def add_issue_count(self, issue_count):
        # Issue count
        self.journal.issue_count = issue_count

    def add_sponsor(self, sponsor):
        # Sponsors
        if not self.journal.sponsors:
            self.journal.sponsors = []
        self.journal.sponsors.append(sponsor)

    def add_contact(self, name, email, address, city, state, country):
        # email to contact
        self.journal.editor_email = email
        self.journal.publisher_address = address
        self.journal.publisher_name = name
        self.journal.publisher_city = city
        self.journal.publisher_state = state
        self.journal.publisher_country = country

    def add_logo_url(self, logo_url):
        self.journal.logo_url = logo_url

    def add_online_submission_url(self, online_submission_url):
        self.journal.online_submission_url = online_submission_url

    def add_related_journals(self, previous_journal, next_journal_title):
        self.journal.next_title = next_journal_title
        self.journal.previous_journal_ref = previous_journal

    def add_event_to_timeline(self, status, since, reason):
        """
        Add item to self.journal.timeline

        Parameters
        ----------
        status : StringField
        since : DateTimeField
        reason : StringField

        """
        if status and since:
            if not self.journal.timeline:
                self.journal.timeline = []

            self.journal.timeline.append(
                Timeline(
                    **{
                        "status": status or "",
                        "since": since or "",
                        "reason": reason or "",
                    }
                )
            )
            self.journal.current_status = self.journal.timeline[-1].status

    def add_mission(self, language, description):
        """
        Add item to self.journal.mission

        Parameters
        ----------
        language : StringField
        description : StringField

        """
        if language and description:
            if not self.journal.mission:
                self.journal.mission = []

            self.journal.mission.append(
                Mission(
                    **{
                        "language": language or "",
                        "description": description or "",
                    }
                )
            )

    def add_metrics(self, total_h5_index, total_h5_median, h5_metric_year):
        """
        Add item to self.journal.metrics

        Parameters
        ----------

        total_h5_index : IntField
        total_h5_median : IntField
        h5_metric_year : IntField

        """
        if all([total_h5_index, total_h5_median, h5_metric_year]):
            self.journal.metrics = JounalMetrics(
                **{
                    "total_h5_index": total_h5_index or None,
                    "total_h5_median": total_h5_median or None,
                    "h5_metric_year": h5_metric_year or None,
                }
            )

    def add_is_public(self):
        self.journal.is_public = True
