import logging

from django.utils.translation import gettext_lazy as _
from scielo_classic_website import classic_ws

from article.controller import create_article
from core.controller import parse_yyyymmdd
from issue.models import Issue
from journal.models import Journal, OfficialJournal
from proc.models import JournalProc
from tracker import choices as tracker_choices


def create_or_update_journal(
    user,
    journal_proc,
    force_update,
):
    """
    Create/update OfficialJournal, JournalProc e Journal
    """
    if (
        journal_proc.migration_status != tracker_choices.PROGRESS_STATUS_TODO
        and not force_update
    ):
        return journal_proc.journal
    collection = journal_proc.collection
    journal_data = journal_proc.migrated_data.data

    # obtém classic website journal
    classic_website_journal = classic_ws.Journal(journal_data)

    year, month, day = parse_yyyymmdd(classic_website_journal.first_year)
    official_journal = OfficialJournal.create_or_update(
        user=user,
        issn_electronic=classic_website_journal.electronic_issn,
        issn_print=classic_website_journal.print_issn,
        title=classic_website_journal.title,
        title_iso=classic_website_journal.title_iso,
        foundation_year=year,
    )
    journal = Journal.create_or_update(
        user=user,
        official_journal=official_journal,
    )
    # TODO
    # for publisher_name in classic_website_journal.raw_publisher_names:
    #     journal.add_publisher(user, publisher_name)

    journal_proc.update(
        user=user,
        journal=journal,
        acron=classic_website_journal.acronym,
        title=classic_website_journal.title,
        availability_status=classic_website_journal.current_status,
        migration_status=tracker_choices.PROGRESS_STATUS_DONE,
        force_update=force_update,
    )
    return journal


def create_or_update_issue(
    user,
    issue_proc,
    force_update,
):
    """
    Create/update Issue
    """
    if (
        issue_proc.migration_status != tracker_choices.PROGRESS_STATUS_TODO
        and not force_update
    ):
        return issue_proc.issue
    classic_website_issue = classic_ws.Issue(issue_proc.migrated_data.data)

    try:
        journal_proc = JournalProc.get(
            collection=issue_proc.collection,
            pid=classic_website_issue.journal,
        )
    except JournalProc.DoesNotExist:
        raise ValueError(
            f"Unable to get journal_proc for issue_proc: {issue_proc}, collection: {issue_proc.collection}, pid={classic_website_issue.journal}"
        )
    if not journal_proc.journal:
        raise ValueError(f"Missing JournalProc.journal for {journal_proc}")

    issue = Issue.get_or_create(
        journal=journal_proc.journal,
        publication_year=classic_website_issue.publication_year,
        volume=classic_website_issue.volume,
        number=classic_website_issue.number,
        supplement=classic_website_issue.supplement,
        user=user,
    )
    issue_proc.update(
        user=user,
        journal_proc=journal_proc,
        issue_folder=classic_website_issue.issue_label,
        issue=issue,
        migration_status=tracker_choices.PROGRESS_STATUS_DONE,
        force_update=force_update,
    )
    return issue


def create_or_update_article(
    user,
    article_proc,
    force_update,
):
    """
    Create/update Issue
    """
    if (
        article_proc.migration_status != tracker_choices.PROGRESS_STATUS_TODO
        and not force_update
    ):
        return article_proc.article

    article = create_article(article_proc.sps_pkg, user, force_update)
    article_proc.migration_status = tracker_choices.PROGRESS_STATUS_DONE
    article_proc.updated_by = user
    article_proc.save()
    return article["article"]
