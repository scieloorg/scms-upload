from opac_schema.v1.models import (
    Journal,
    Timeline,
    SocialNetwork,
    OtherTitle,
    Mission,
    JounalMetrics,
    LastIssue,
)

from libs.dsm.publication import db


def get_journal(scielo_issn):
    """
    Get registered journal or new journal

    Parameters
    ----------
    scielo_issn : str

    Raises
    ------
    exceptions.RecordNotFoundError

    Returns
    -------
    Journal
    """
    journal = db.fetch_record(scielo_issn, Journal)
    if not journal:
        journal = Journal()
        journal._id = scielo_issn
    return journal


def add_item_to_timeline(journal, input_status, input_since, input_reason):
    """
    Add item to journal.timeline

    Parameters
    ----------
    journal : Journal
    input_status : StringField
    input_since : DateTimeField
    input_reason : StringField

    """
    if input_status and input_since:
        if not journal.timeline:
            journal.timeline = []

        journal.timeline.append(
            Timeline(**{
                'status': input_status or '',
                'since': input_since or '',
                'reason': input_reason or '',
            })
        )
