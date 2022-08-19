from libs.dsm.classic_ws import classic_ws
from libs.dsm.publication.journals import JournalToPublish
from libs.dsm.publication import db
from libs.dsm.publication.exceptions import PublishJournalError

from .models import JournalMigrationTracker, MigratedJournal
from .choices import MS_MIGRATED, MS_PUBLISHED
from .exceptions import (
    JournalMigrationTrackSaveError,
    MigratedJournalSaveError,
)


def connect(connection):
    host = connection.get("host")
    alias = connection.get("alias")
    return db.mk_connection(host, alias=alias)


def get_classic_website_records(db_type, source_file_path):
    return classic_ws.get_records_by_source_path(db_type, source_file_path)


def get_migrated_journal(**kwargs):
    try:
        j = MigratedJournal.objects.get(**kwargs)
    except MigratedJournal.DoesNotExist:
        j = MigratedJournal()
    return j


def get_journal_migration_tracker(scielo_issn):
    try:
        j = JournalMigrationTracker.objects.get(scielo_issn=scielo_issn)
    except JournalMigrationTracker.DoesNotExist:
        j = JournalMigrationTracker()
        j.scielo_issn = scielo_issn
    return j


def migrate_journal(journal_id, data):
    """
    Create/update MigratedJournal e JournalMigrationTracker

    """
    try:
        classic_ws_j = classic_ws.Journal(data)

        migrated = get_migrated_journal(scielo_issn=journal_id)
        migrated.scielo_issn = journal_id
        migrated.acron = classic_ws_j.acron
        migrated.title = classic_ws_j.title
        migrated.record = data
        migrated.save()
    except Exception as e:
        raise MigratedJournalSaveError(
            "Unable to save migrated journal %s %s" %
            (journal_id, e)
        )

    try:
        journal_migration = get_journal_migration_tracker(journal_id)
        journal_migration.acron = classic_ws_j.acron
        journal_migration.isis_created_date = classic_ws_j.isis_created_date
        journal_migration.isis_updated_date = classic_ws_j.isis_updated_date
        journal_migration.status = MS_MIGRATED
        journal_migration.journal = migrated

        journal_migration.save()
    except Exception as e:
        raise JournalMigrationTrackSaveError(
            "Unable to save journal migration track %s %s" %
            (journal_id, e)
        )


def publish_journal(journal_id):
    """
    Raises
    ------
    PublishJournalError
    """
    try:
        journal_migration = JournalMigrationTracker.objects.get(
            scielo_issn=journal_id)
    except JournalMigrationTracker.DoesNotExist as e:
        raise PublishJournalError(
            "JournalMigrationTracker does not exists %s %s" % (journal_id, e))

    try:
        classic_ws_j = classic_ws.Journal(journal_migration.journal.record)

        journal_to_publish = JournalToPublish()

        journal_to_publish.add_contact(
            classic_ws_j.publisher_name,
            classic_ws_j.publisher_email,
            classic_ws_j.publisher_address,
            classic_ws_j.publisher_city,
            classic_ws_j.publisher_state,
            classic_ws_j.publisher_country,
        )
        for lang, text in classic_ws_j.mission.items():
            journal_to_publish.add_item_to_mission(lang, text)

        for item in classic_ws_j.status_history:
            journal_to_publish.add_item_to_timeline(
                item["status"], item["since"], item["reason"],
            )
        journal_to_publish.add_journal_issns(
            classic_ws_j.scielo_issn,
            classic_ws_j.electronic_issn,
            classic_ws_j.print_issn,
        )
        journal_to_publish.add_journal_titles(
            classic_ws_j.title,
            classic_ws_j.abbreviated_iso_title,
            classic_ws_j.abbreviated_title,
        )

        journal_to_publish.add_online_submission_url(classic_ws_j.submission_url)

        previous_journal = next_journal_title = None
        if classic_ws_j.previous_title:
            previous_journal = get_migrated_journal(
                title=classic_ws_j.previous_title)
            if not previous_journal.scielo_issn:
                previous_journal = None
        if classic_ws_j.next_title:
            next_journal = get_migrated_journal(title=classic_ws_j.next_title)
            if next_journal.scielo_issn:
                next_journal_title = classic_ws_j.next_title
        if previous_journal or next_journal_title:
            journal_to_publish.add_related_journals(
                previous_journal, next_journal_title,
            )
        for item in classic_ws_j.sponsors:
            journal_to_publish.add_sponsor(item)

        # TODO confirmar se subject_categories é subject_descriptors
        journal_to_publish.add_thematic_scopes(
            classic_ws_j.subject_descriptors, classic_ws_j.subject_areas,
        )

        # classic_ws_j não tem este dado
        # journal_to_publish.add_issue_count(
        #     classic_ws_j.issue_count,
        # )

        # classic_ws_j não tem este dado
        # journal_to_publish.add_item_to_metrics(
        #     classic_ws_j.total_h5_index,
        #     classic_ws_j.total_h5_median,
        #     classic_ws_j.h5_metric_year,
        # )
        # classic_ws_j não tem este dado
        # journal_to_publish.add_logo_url(classic_ws_j.logo_url)

        journal_to_publish.publish_journal()
    except Exception as e:
        raise PublishJournalError(
            "Unable to publish %s %s" % (journal_id, e)
        )

    try:
        journal_migration.status = MS_PUBLISHED
        journal_migration.save()
    except Exception as e:
        raise PublishJournalError(
            "Unable to upate journal_migration status %s %s" % (journal_id, e)
        )

