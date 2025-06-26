"""
Facade para manter compatibilidade com o código existente.
Este módulo importa todas as funções dos novos módulos especializados.
"""
from proc.models import JournalProc, IssueProc

# Imports da API Core
from proc.source_core_api import (
    create_or_update_journal,
    create_or_update_issue,
    fetch_and_create_journal,
    fetch_and_create_issues,
    FetchMultipleJournalsError,
    UnableToGetJournalDataFromCoreError,
    FetchJournalDataException,
    FetchIssueDataException,
)

# Imports do Classic Website
from proc.source_classic_website import (
    create_or_update_migrated_journal,
    create_or_update_migrated_issue,
    create_collection_procs_from_pid_list,
    migrate_journal,
    create_or_update_journal_acron_id_file,
    migrate_issue,
    migrate_document_records,
    get_files_from_classic_website,
)

# Imports de Publication
from proc.publisher import (
    publish_journals,
    publish_issues,
    publish_articles,
)

# Imports de Exceptions
from proc.exceptions import (
    ProcBaseException,
    UnableToCreateIssueProcsError,
)

# Mantém a interface pública existente para backward compatibility
__all__ = [
    # Core API functions
    "create_or_update_journal",
    "create_or_update_issue",
    "fetch_and_create_journal",
    "fetch_and_create_issues",
    # Classic Website functions
    "create_or_update_migrated_journal",
    "create_or_update_migrated_issue",
    "create_collection_procs_from_pid_list",
    "migrate_journal",
    "create_or_update_journal_acron_id_file",
    "migrate_issue",
    "migrate_document_records",
    "get_files_from_classic_website",
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
    """
    Verifica e garante a existência de JournalProc para o journal

    Args:
        user: O usuário que executa a operação
        journal: O journal que deve ter um JournalProc

    Returns:
        JournalProc: O objeto JournalProc existente ou recém-criado

    Raises:
        JournalProc.DoesNotExist: Se não foi possível criar JournalProc
    """
    # Verificar se já existe
    journal_procs = JournalProc.objects.filter(journal=journal, acron__isnull=False)
    if journal_procs.exists():
        return journal_procs.first()

    # Não existe, criar um novo
    create_or_update_journal(
        journal_title=journal.title,
        issn_electronic=journal.official_journal.issn_electronic,
        issn_print=journal.official_journal.issn_print,
        user=user,
        force_update=True,
    )

    # Verificar se foi criado
    journal_procs = JournalProc.objects.filter(journal=journal)
    if journal_procs.exists():
        return journal_procs.first()

    raise JournalProc.DoesNotExist(f"JournalProc does not exist: {journal}")


def ensure_issue_proc_exists(user, issue):
    """
    Verifica e garante a existência de IssueProc para o issue

    Args:
        user: O usuário que executa a operação
        issue: O issue que deve ter um IssueProc

    Returns:
        IssueProc: O objeto IssueProc existente ou recém-criado

    Raises:
        IssuePrerequisiteError: Se não foi possível criar IssueProc
    """
    # Verificar se o IssueProc já existe
    issue_procs = IssueProc.objects.filter(issue=issue)
    if issue_procs.exists():
        return issue_procs.first()

    # Não existe, criar um novo
    create_or_update_issue(
        journal=issue.journal,
        pub_year=issue.publication_year,
        volume=issue.volume,
        suppl=issue.supplement,
        number=issue.number,
        user=user,
        force_update=True,
    )

    # Verificar se foi criado
    issue_procs = IssueProc.objects.filter(issue=issue)
    if issue_procs.exists():
        return issue_procs.first()

    raise IssueProc.DoesNotExist(f"IssueProc does not exist: {issue}")
