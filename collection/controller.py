from django.utils.translation import gettext_lazy as _

from .models import (
    Collection,
    JournalCollections,
    SciELOJournal,
)
from journal.controller import get_or_create_official_journal

from . import exceptions


def get_or_create_collection(collection_acron):
    try:
        collection, status = Collection.objects.get_or_create(
            acron=collection_acron
        )
    except Exception as e:
        raise exceptions.GetOrCreateCollectionError(
            _('Unable to get_or_create_collection {} {} {}').format(
                collection_acron, type(e), e
            )
        )
    return collection


def get_or_create_scielo_journal(collection, scielo_issn):
    try:
        scielo_journal, status = SciELOJournal.objects.get_or_create(
            collection=collection, scielo_issn=scielo_issn,
        )
    except Exception as e:
        raise exceptions.GetOrCreateScieloJournalError(
            _('Unable to get_or_create_scielo_journal {} {} {} {}').format(
                collection, scielo_issn, type(e), e
            )
        )
    return scielo_journal


def get_or_create_journal_collections(official_journal):
    try:
        scielo_journal, status = JournalCollections.objects.get_or_create(
            official_journal=official_journal,
        )
    except Exception as e:
        raise exceptions.GetOrCreateJournalCollectionsError(
            _('Unable to get_or_create_journal_collections {} {} {}').format(
                official_journal, type(e), e
            )
        )
    return scielo_journal


def get_or_create_scielo_journal_in_journal_collections(official_journal, scielo_journal):

    try:
        journal_collections = get_or_create_journal_collections(official_journal)

    except Exception as e:
        raise exceptions.GetOrCreateScieloJournalInJournalCollectionsError(
            _('Unable to get_or_create_scielo_journal_in_journal_collections {} {} {} {}').format(
                official_journal, scielo_journal, type(e), e
            )
        )
    journal_collections.scielo_journals.get_or_create(scielo_journal)
    return journal_collections

