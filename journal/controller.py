import logging

from django.utils.translation import gettext_lazy as _

from journal.models import OfficialJournal

from . import exceptions

arg_names = (
    "title",
    "ISSN_electronic",
    "ISSN_print",
    "ISSNL",
)


def _get_args(names, values):
    return {k: v for k, v in zip(names, values) if v}


def get_or_create_official_journal(title, issn_l, e_issn, print_issn, creator_id):
    if not any([title, e_issn, print_issn, issn_l]):
        raise exceptions.GetOrCreateOfficialJournalError(
            "collections.get_or_create_official_journal requires title or e_issn or print_issn or issn_l"
        )

    kwargs = _get_args(arg_names, (title, e_issn, print_issn, issn_l))
    try:
        logging.info(
            "Get or create Official Journal {} {} {} {}".format(
                title, issn_l, e_issn, print_issn
            )
        )
        official_journal = OfficialJournal.objects.get(**kwargs)
        logging.info("Got {}".format(official_journal))
    except OfficialJournal.DoesNotExist:
        logging.info("DoesNotExist")
        official_journal = OfficialJournal()
        official_journal.title = title
        official_journal.ISSNL = issn_l
        official_journal.ISSN_electronic = e_issn
        official_journal.ISSN_print = print_issn
        official_journal.creator_id = creator_id
        official_journal.save()
        logging.info("Created {}".format(official_journal))
    except Exception as e:
        raise exceptions.GetOrCreateOfficialJournalError(
            _("Unable to get or create official journal {} {} {} {} {} {}").format(
                title, issn_l, e_issn, print_issn, type(e), e
            )
        )
    return official_journal


def get_journal_dict_for_validation(journal_id):
    data = {}

    try:
        journal = OfficialJournal.objects.get(pk=journal_id)
        data["titles"] = [
            t
            for t in [
                journal.title,
                journal.title_iso,
                journal.short_title,
                journal.nlm_title,
            ]
            if t is not None and len(t) > 0
        ]
        data["print_issn"] = journal.ISSN_print
        data["electronic_issn"] = journal.ISSN_electronic
    except OfficialJournal.DoesNotExist:
        ...

    return data
