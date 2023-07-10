import logging

from django.utils.translation import gettext_lazy as _

from journal.models import OfficialJournal

from . import exceptions


# TODO substituir esta função por outra abordagem / Usar Journal
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
