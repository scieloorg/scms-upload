import logging

from django.utils.translation import gettext_lazy as _

from issue.models import Issue

from . import exceptions


arg_names = (
    "official_journal",
    "volume",
    "number",
    "supplement",
)


def _get_args(names, values):
    return {k: v or "" for k, v in zip(names, values) if v}


def get_or_create_official_issue(
    official_journal,
    year,
    volume,
    number,
    supplement,
    creator_id,
    initial_month_name=None,
    initial_month_number=None,
    final_month_name=None,
):
    values = (
        official_journal,
        volume,
        number,
        supplement,
    )
    if not any(values):
        raise exceptions.GetOrCreateIssueError(
            _(
                "collections.get_or_create_official_issue requires "
                "official_journal or volume or number or supplement"
            )
        )

    kwargs = _get_args(arg_names, values)
    try:
        try:
            logging.info("Get or create official issue")
            logging.info(kwargs)
            official_issue = Issue.objects.get(**kwargs)
            logging.info("Got official_issue")
        except Issue.DoesNotExist:
            logging.info("DoesNotExist")
            official_issue = Issue()
            official_issue.creator_id = creator_id
            official_issue.official_journal = official_journal
            official_issue.volume = volume
            official_issue.number = number
            official_issue.supplement = supplement
            official_issue.publication_year = year
            official_issue.publication_initial_month_number = initial_month_number
            official_issue.publication_initial_month_name = initial_month_name
            official_issue.publication_final_month_name = final_month_name
            official_issue.save()
            logging.info("Created official_issue")
    except Exception as e:
        raise exceptions.GetOrCreateIssueError(
            _("Unable to get or create official issue {} {} {}").format(
                str(values), type(e), e
            )
        )
    return official_issue
