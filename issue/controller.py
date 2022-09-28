from django.utils.translation import gettext_lazy as _

from issue.models import Issue

from . import exceptions


arg_names = (
    'official_journal',
    'year',
    'volume',
    'number',
    'supplement',
)


def _get_args(names, values):
    return {
        k: v or ''
        for k, v in zip(names, values)
    }


def get_or_create_official_issue(official_journal,
                                 year,
                                 volume,
                                 number,
                                 supplement,
                                 creator_id,
                                 ):
    values = (official_journal, year, volume, number, supplement, )
    if not any(values):
        raise exceptions.GetOrCreateIssueError(
            _("collections.get_or_create_official_issue requires "
              "official_journal or year or volume or number or supplement")
        )

    kwargs = _get_args(arg_names, values)
    try:
        try:
            official_issue = Issue.objects.get(**kwargs)
        except Issue.DoesNotExist:
            official_issue = Issue()
            official_issue.creator_id = creator_id
            official_issue.official_journal = official_journal
            official_issue.year = year
            official_issue.volume = volume
            official_issue.number = number
            official_issue.supplement = supplement
            official_issue.save()
    except Exception as e:
        raise exceptions.GetOrCreateIssueError(
            _('Unable to get or create official issue {} {} {}').format(
                str(values), type(e), e
            )
        )
    return official_issue
