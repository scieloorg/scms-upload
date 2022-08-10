from opac_schema.v1.models import (
    Journal,
    Timeline,
    SocialNetwork,
    OtherTitle,
    Mission,
    JounalMetrics,
    LastIssue,
)


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


def add_item_to_mission(journal, input_language, input_text):
    """
    Add item to journal.mission

    Parameters
    ----------
    journal : Journal
    input_language : StringField
    input_text : DateTimeField

    """
    if input_language and input_text:
        if not journal.mission:
            journal.mission = []

        journal.mission.append(
            Mission(**{
                'language': input_language or '',
                'description': input_text or '',
            })
        )
