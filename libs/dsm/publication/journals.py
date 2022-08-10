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
