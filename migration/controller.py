from libs.dsm.classic_ws import classic_ws
from libs.dsm.publication.journals import JournalToPublish
from libs.dsm.publication.issues import IssueToPublish, get_bundle_id
from libs.dsm.publication import db
from libs.dsm.publication.exceptions import (
    PublishJournalError,
    PublishIssueError,
    JournalPublicationForbidden,
    IssuePublicationForbidden,
)

from .models import (
    JournalMigrationTracker, MigratedJournal,
    IssueMigrationTracker, MigratedIssue,
)
from .choices import MS_MIGRATED, MS_PUBLISHED
from .exceptions import (
    JournalMigrationTrackSaveError,
    MigratedJournalSaveError,
    IssueMigrationTrackSaveError,
    MigratedIssueSaveError,
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


def get_journal_migration_tracker(**kwargs):
    try:
        j = JournalMigrationTracker.objects.get(**kwargs)
    except JournalMigrationTracker.DoesNotExist:
        j = JournalMigrationTracker()
    return j


def migrate_journal(journal_id, data, force_update=False):
    """
    Create/update MigratedJournal e JournalMigrationTracker

    """
    journal_migration = get_journal_migration_tracker(scielo_issn=journal_id)
    classic_ws_j = classic_ws.Journal(data)

    if not force_update:
        # check if it needs to be update
        if journal_migration.isis_updated_date == classic_ws_j.isis_updated_date:
            # nao precisa atualizar
            return

    try:
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

    if journal_migration.status != MS_MIGRATED:
        raise JournalPublicationForbiddenError(
            "JournalMigrationTracker.status of %s is not MS_MIGRATED" %
            journal_id
        )

    try:
        classic_ws_j = classic_ws.Journal(journal_migration.journal.record)

        journal_to_publish = JournalToPublish(journal_id)

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


##################################################################
# ISSUE

def get_migrated_issue(**kwargs):
    try:
        j = MigratedIssue.objects.get(**kwargs)
    except MigratedIssue.DoesNotExist:
        j = MigratedIssue()
    return j


def get_issue_migration_tracker(**kwargs):
    try:
        j = IssueMigrationTracker.objects.get(**kwargs)
    except IssueMigrationTracker.DoesNotExist:
        j = IssueMigrationTracker()
    return j


def migrate_issue(issue_pid, data, force_update=False):
    """
    Create/update MigratedIssue e IssueMigrationTracker

    """
    issue_migration = get_issue_migration_tracker(issue_pid=issue_pid)
    classic_ws_i = classic_ws.Issue(data)

    if not force_update:
        # check if it needs to be update
        if issue_migration.isis_updated_date == classic_ws_i.isis_updated_date:
            # nao precisa atualizar
            return
    try:
        migrated = get_migrated_issue(issue_pid=issue_pid)
        migrated.issue_pid = issue_pid
        migrated.record = data
        migrated.save()
    except Exception as e:
        raise MigratedIssueSaveError(
            "Unable to save migrated issue %s %s" %
            (issue_pid, e)
        )

    try:
        issue_migration.acron = classic_ws_i.acron
        issue_migration.isis_created_date = classic_ws_i.isis_created_date
        issue_migration.isis_updated_date = classic_ws_i.isis_updated_date
        issue_migration.status = MS_MIGRATED
        issue_migration.migrated_issue = migrated

        issue_migration.save()
    except Exception as e:
        raise IssueMigrationTrackSaveError(
            "Unable to save issue migration track %s %s" %
            (issue_pid, e)
        )


def publish_issue(issue_pid):
    """
    Raises
    ------
    PublishIssueError
    """
    try:
        issue_migration = IssueMigrationTracker.objects.get(
            pid=issue_pid)
    except IssueMigrationTracker.DoesNotExist as e:
        raise PublishIssueError(
            "IssueMigrationTracker does not exists %s %s" % (issue_pid, e))

    if issue_migration.status != MS_MIGRATED:
        raise IssuePublicationForbiddenError(
            "IssueMigrationTracker.status of %s is not MS_MIGRATED" %
            issue_pid
        )

    try:
        classic_ws_i = classic_ws.Issue(issue_migration.migrated_issue.record)
        published_id = get_bundle_id(
            classic_ws_i.journal,
            classic_ws_i.year,
            classic_ws_i.volume,
            classic_ws_i.number,
            classic_ws_i.supplement,
        )
        issue_to_publish = IssueToPublish(published_id)

        issue_to_publish.add_identification(
            classic_ws_i.volume,
            classic_ws_i.number,
            classic_ws_i.supplement)
        issue_to_publish.add_journal(classic_ws_i.journal)
        issue_to_publish.add_order(int(classic_ws_i.order[4:]))
        issue_to_publish.add_pid(classic_ws_i.pid)
        issue_to_publish.add_publication_date(
            classic_ws_i.year,
            classic_ws_i.start_month,
            classic_ws_i.end_month)
        issue_to_publish.has_docs = []

        issue_to_publish.publish_issue()
    except Exception as e:
        raise PublishIssueError(
            "Unable to publish %s %s" % (issue_pid, e)
        )

    try:
        issue_migration.status = MS_PUBLISHED
        issue_migration.save()
    except Exception as e:
        raise PublishIssueError(
            "Unable to upate issue_migration status %s %s" % (issue_pid, e)
        )

