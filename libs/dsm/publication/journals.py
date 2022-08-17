from opac_schema.v1.models import (
    Journal,
    Timeline,
    Mission,
    JounalMetrics,
)
from . import exceptions


def get_journal(journal_id):
    """
    Get registered journal or new journal

    Parameters
    ----------
    journal_id : str

    Returns
    -------
    Journal
    """
    try:
        journal = Journal.objects.get(_id=journal_id)
    except Journal.DoesNotExist:
        journal = Journal()
        journal._id = journal_id
    return journal


def add_item_to_timeline(journal, status, since, reason):
    """
    Add item to journal.timeline

    Parameters
    ----------
    journal : Journal
    status : StringField
    since : DateTimeField
    reason : StringField

    """
    if status and since:
        if not journal.timeline:
            journal.timeline = []

        journal.timeline.append(
            Timeline(**{
                'status': status or '',
                'since': since or '',
                'reason': reason or '',
            })
        )


def add_item_to_mission(journal, language, description):
    """
    Add item to journal.mission

    Parameters
    ----------
    journal : Journal
    language : StringField
    description : StringField

    """
    if language and description:
        if not journal.mission:
            journal.mission = []

        journal.mission.append(
            Mission(**{
                'language': language or '',
                'description': description or '',
            })
        )


def add_item_to_metrics(journal, total_h5_index, total_h5_median, h5_metric_year):
    """
    Add item to journal.metrics

    Parameters
    ----------
    journal : Journal

    total_h5_index : IntField
    total_h5_median : IntField
    h5_metric_year : IntField

    """
    journal.metrics = None
    if all([total_h5_index, total_h5_median, h5_metric_year]):
        journal.metrics = (
            JounalMetrics(**{
                'total_h5_index': total_h5_index or 0,
                'total_h5_median': total_h5_median or 0,
                'h5_metric_year': h5_metric_year or 0,
            })
        )


def publish_journal(journal_data):
    """
    Publishes journal data

    Parameters
    ----------
    journal_data : dict

    Raises
    ------
    JournalDataError
    JournalSaveError

    Returns
    -------
    Journal
    """

    try:
        journal = get_journal(journal_data["id"])

        journal.title = journal_data["title"]
        journal.title_iso = journal_data["title_iso"]
        journal.short_title = journal_data["short_title"]
        journal.acronym = journal_data["acronym"]
        journal.scielo_issn = journal_data["scielo_issn"]
        journal.print_issn = journal_data.get("print_issn", "")
        journal.eletronic_issn = journal_data.get("electronic_issn", "")

        # Subject Categories
        journal.subject_categories = journal_data["subject_categories"]

        # Métricas
        item = journal_data.get("metrics")
        if item:
            add_item_to_metrics(journal,
                                item['total_h5_index'],
                                item['total_h5_median'],
                                item['h5_metric_year'])

        # Issue count
        journal.issue_count = journal_data["issue_count"]

        # Mission
        for item in journal_data["mission"]:
            add_item_to_mission(journal, item['language'], item['description'])

        # Study Area
        journal.study_areas = journal_data["subject_areas"]

        # Sponsors
        journal.sponsors = journal_data["sponsors"]

        # email to contact
        journal.editor_email = journal_data["contact"]["email"]
        journal.publisher_address = journal_data["contact"]["address"]

        journal.publisher_name = journal_data["publisher"]["name"]
        journal.publisher_city = journal_data["publisher"]["city"]
        journal.publisher_state = journal_data["publisher"]["state"]
        journal.publisher_country = journal_data["publisher"]["country"]

        journal.online_submission_url = journal_data.get("online_submission_url", "")

        journal.logo_url = journal_data.get("logo_url", "")

        for item in journal_data["status_history"]:
            add_item_to_timeline(journal,
                                 item["status"],
                                 item["since"],
                                 item["reason"],
                                 )
        journal.current_status = journal_data.timeline[-1].get("status")
        journal.next_title = journal_data.get("next_journal")
        journal.previous_journal_ref = journal_data.get("previous_journal")

    except KeyError as e:
        raise exceptions.JournalDataError(e)

    try:
        journal.save()
    except Exception as e:
        raise exceptions.JournalSaveError(e)

    return journal
