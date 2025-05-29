"""
Facade para manter compatibilidade com o código existente.
Este módulo importa todas as funções dos novos módulos especializados.
"""

# Imports da API Core
from .source_core_api import (
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
from .source_classic_website import (
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
from .publisher import (
    publish_journals,
    publish_issues,
    publish_articles,
)

# Imports de Exceptions
from .exceptions import (
    ProcBaseException,
    UnableToCreateIssueProcsError,
)

# Mantém a interface pública existente para backward compatibility
__all__ = [
    # Core API functions
    'create_or_update_journal',
    'create_or_update_issue',
    'fetch_and_create_journal',
    'fetch_and_create_issues',
    
    # Classic Website functions
    'create_or_update_migrated_journal',
    'create_or_update_migrated_issue',
    'create_collection_procs_from_pid_list', 
    'migrate_journal',
    'create_or_update_journal_acron_id_file',
    'migrate_issue',
    'migrate_document_records',
    'get_files_from_classic_website',
    
    # Publication functions
    'publish_journals',
    'publish_issues', 
    'publish_articles',
    
    # Exceptions
    'FetchMultipleJournalsError',
    'UnableToGetJournalDataFromCoreError',
    'UnableToCreateIssueProcsError',
    'FetchJournalDataException',
    'FetchIssueDataException',
    'ProcBaseException',
]