"""
Facade para manter compatibilidade com o código existente.
Este módulo importa todas as funções dos novos módulos especializados.
"""

from proc.models import JournalProc, IssueProc, ArticleProc

# Imports de Exceptions
from proc.exceptions import (
    ProcBaseException,
    UnableToCreateIssueProcsError,
)

# Imports de Publication
from proc.publisher import (
    publish_articles,
    publish_issues,
    publish_journals,
)

# Imports do Classic Website
from proc.source_classic_website import (
    create_or_update_migrated_issue,
    create_or_update_migrated_journal,
    migrate_issue,
    migrate_journal,
)

# Imports da API Core
from proc.source_core_api import (
    BaseDataChecker,
    FetchIssueDataException,
    FetchJournalDataException,
    FetchMultipleJournalsError,
    IssueDataChecker,
    JournalDataChecker,
    UnableToGetJournalDataFromCoreError,
    create_or_update_issue,
    create_or_update_journal,
    fetch_and_create_issues,
    fetch_and_create_journal,
)

# Mantém a interface pública existente para backward compatibility
__all__ = [
    # Core API functions
    "create_or_update_journal",
    "create_or_update_issue",
    "fetch_and_create_journal",
    "fetch_and_create_issues",
    # Core API classes
    "BaseDataChecker",
    "JournalDataChecker",
    "IssueDataChecker",
    # Classic Website functions
    "create_or_update_migrated_journal",
    "create_or_update_migrated_issue",
    "migrate_journal",
    "migrate_issue",
    # Publication functions
    "publish_journals",
    "publish_issues",
    "publish_articles",
    # Exceptions
    "FetchMultipleJournalsError",
    "UnableToGetJournalDataFromCoreError",
    "UnableToCreateIssueProcsError",
    "FetchJournalDataException",
    "FetchIssueDataException",
    "ProcBaseException",
]


def ensure_journal_proc_exists(user, journal):
    """Delega para JournalDataChecker.ensure_proc_exists."""
    return JournalDataChecker.ensure_proc_exists(user, journal)


def ensure_issue_proc_exists(user, issue):
    """Delega para IssueDataChecker.ensure_proc_exists."""
    return IssueDataChecker.ensure_proc_exists(user, issue)


def get_total_status_data(journal_proc_id, total_status_data):
    journal_total_status = JournalProc.get_total_status(journal_proc_id)
    issue_total_status = IssueProc.get_total_status(journal_proc_id, "article")
    article_total_status = ArticleProc.get_total_status(journal_proc_id)
    
    total_status_data_updated = {}
    if journal_total_status != total_status_data.get("journal"):
        total_status_data_updated["journal"] = journal_total_status
    if issue_total_status != total_status_data.get("issue"):
        total_status_data_updated["issue"] = issue_total_status
    if article_total_status != total_status_data.get("article"):
        total_status_data_updated["article"] = article_total_status

    return total_status_data_updated