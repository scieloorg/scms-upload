"""
Facade para manter compatibilidade com o código existente.
Este módulo importa todas as funções dos novos módulos especializados.
"""

# Imports de Exceptions
from proc.exceptions import (
    ProcBaseException,
    UnableToCreateIssueProcsError,
)
from proc.models import IssueProc, JournalProc

# Imports de Publication
from proc.publisher import (
    publish_articles,
    publish_issues,
    publish_journals,
)

# Imports do Classic Website
from proc.source_classic_website import (
    create_collection_procs_from_pid_list,
    create_or_update_journal_acron_id_file,
    create_or_update_migrated_issue,
    create_or_update_migrated_journal,
    get_files_from_classic_website,
    migrate_document_records,
    migrate_issue,
    migrate_journal,
)

# Imports da API Core
from proc.source_core_api import (
    FetchIssueDataException,
    FetchJournalDataException,
    FetchMultipleJournalsError,
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
    if (
        journal.missing_fields
        or not JournalProc.objects.filter(journal=journal, acron__isnull=False).exists()
    ):
        # Não existe, criar um novo
        create_or_update_journal(
            journal_title=journal.title,
            issn_electronic=journal.official_journal.issn_electronic,
            issn_print=journal.official_journal.issn_print,
            user=user,
            force_update=True,
        )

    journal_proc = JournalProc.objects.filter(
        journal=journal, acron__isnull=False
    ).first()
    if journal_proc:
        if not journal.journal_acron:
            journal.journal_acron = journal_proc.acron
            journal.save()
        return True

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
    if IssueProc.objects.filter(issue=issue).exists():
        return True

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
    if IssueProc.objects.filter(issue=issue).exists():
        return True

    raise IssueProc.DoesNotExist(f"IssueProc does not exist: {issue}")
