from django.utils.translation import gettext_lazy as _

from journal.models import OfficialJournal

from . import exceptions


arg_names = (
    'ISSN_electronic',
    'ISSN_print',
    'ISSNL',
)


def _get_args(names, values):
    return {
        k: v
        for k, v in zip(names, values)
        if v
    }


def get_or_create_official_journal(issn_l, e_issn, print_issn):
    if not any([e_issn, print_issn, issn_l]):
        raise exceptions.GetOfficialJournalError(
            "collections.get_or_create_official_journal requires e_issn or print_issn or issn_l"
        )

    kwargs = _get_args(arg_names, (e_issn, print_issn, issn_l))
    try:
        official_journal, status = OfficialJournal.objects.get_or_create(**kwargs)
    except Exception as e:
        raise exceptions.GetOrCreateOfficialJournalError(
            _('Unable to get or create official journal {} {} {} {} {}').format(
                issn_l, e_issn, print_issn, type(e), e
            )
        )
    return official_journal


def get_journal_dict_for_validation(journal_id):
    data = {}

    try:
        journal = OfficialJournal.objects.get(pk=journal_id)
        data['titles'] = [journal.title,]
        data['print_issn'] = journal.ISSN_print
        data['electronic_issn'] = journal.ISSN_electronic
    except OfficialJournal.DoesNotExist:
        ...

    return data
