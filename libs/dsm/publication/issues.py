from opac_schema.v1.models import (
    Issue,
)
from . import exceptions


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
