from opac_schema.v1.models import (
    Issue,
    Journal,
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


def _set_issue_type(issue):

    if issue.suppl_text:
        issue.type = "supplement"
        return

    if issue.volume and not issue.number:
        issue.type = "volume_issue"

    if issue.number == "ahead":
        issue.type == "ahead"
        issue.year = "9999"
        return

    if issue.number and "spe" in issue.number:
        issue.type = "special"
        return


def _get_issue_label(issue_data: dict) -> str:
    """Produz o label esperado pelo OPAC de acordo com as regras aplicadas
    pelo OPAC Proc e Xylose.
    Args:
        issue_data (dict): conteúdo de um bundle
    Returns:
        str: label produzido a partir de um bundle
    """
    prefixes = ("v", "n", "s")
    names = ("volume", "number", "supplement")
    return "".join(
        f"{prefix}{issue_data.get(name)}"
        for prefix, name in zip(prefixes, names)
        if issue_data.get(name)
    )


def publish_issue(issue_data):
    """
    Publishes issue data

    Parameters
    ----------
    issue_data : dict

    Raises
    ------
    IssueDataError
    IssueSaveError

    Returns
    -------
    Issue
    """
    issue = get_issue(issue_data.get("id"))

    try:
        issue.journal = Journal.objects.get(_id=issue_data["journal_id"])

        issue._id = issue.iid = issue_data["id"]
        issue.order = issue_data["issue_order"]
        issue.pid = issue_data["issue_pid"]

        try:
            publication_date = issue_data["publication_date"]
        except KeyError:
            raise exceptions.IssueDataError(e)
        else:
            try:
                months = publication_date["months"]
            except KeyError:
                raise exceptions.IssueDataError(e)
            else:
                issue.start_month = months["start"]
                issue.end_month = months["end"]

        issue.year = publication_date["year"]
        issue.volume = issue_data.get("volume")
        issue.number = issue_data.get("number")
        issue.spe_text = issue_data.get("spe_text")
        issue.suppl_text = issue_data.get("supplement")

        issue.label = _get_issue_label(issue_data) or None

        if issue.type == "ahead" and not issue_data.get("docs"):
            """
            Caso não haja nenhum artigo no bundle de ahead, ele é definido como
            ``outdated_ahead``, para que não apareça na grade de fascículos
            """
            issue.type = "outdated_ahead"

    except KeyError as e:
        raise exceptions.IssueDataError(e)

    try:
        issue.save()
    except Exception as e:
        raise exceptions.IssueSaveError(e)

    return issue
