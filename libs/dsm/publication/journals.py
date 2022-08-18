from opac_schema.v1.models import (
    Journal,
    Timeline,
    Mission,
    JounalMetrics,
)
from . import exceptions
from .db import save_data


def get_journal(journal_id):
    """
    Get registered journal or new journal

    Parameters
    ----------
    journal_id : str

    Returns
    -------
    opac_schema.v1.models.Journal
    """
    try:
        journal = Journal.objects.get(_id=journal_id)
    except Journal.DoesNotExist:
        journal = Journal()
        journal._id = journal_id
    return journal


class JournalToPublish:
    def __init__(self, journal_id):
        self.journal = get_journal(journal_id)

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

    def add_item_to_timeline(self, status, since, reason):
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
                Timeline(**{
                    'status': status or '',
                    'since': since or '',
                    'reason': reason or '',
                })
            )
            self.journal.current_status = (
                self.journal.timeline[-1].get("status")
            )

    def add_item_to_mission(self, language, description):
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
                Mission(**{
                    'language': language or '',
                    'description': description or '',
                })
            )

    def add_item_to_metrics(self, total_h5_index, total_h5_median, h5_metric_year):
        """
        Add item to self.journal.metrics

        Parameters
        ----------

        total_h5_index : IntField
        total_h5_median : IntField
        h5_metric_year : IntField

        """
        if all([total_h5_index, total_h5_median, h5_metric_year]):
            self.journal.metrics = (
                JounalMetrics(**{
                    'total_h5_index': total_h5_index or 0,
                    'total_h5_median': total_h5_median or 0,
                    'h5_metric_year': h5_metric_year or 0,
                })
            )

    def publish_journal(self):
        """
        Publishes journal data

        Parameters
        ----------
        journal_data : dict

        Raises
        ------
        JournalSaveError

        Returns
        -------
        opac_schema.v1.models.Journal
        """

        try:
            save_data(self.journal)
        except Exception as e:
            raise exceptions.JournalSaveError(e)

        return self.journal
