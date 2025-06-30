"""
Módulo responsável pela busca e processamento de dados da API Core externa.
"""

import logging
import sys
from django.conf import settings
from django.db.models import Q

from core.utils.requester import fetch_data
from journal.models import (
    Journal,
    OfficialJournal,
    Subject,
    Institution,
    Publisher,
    Owner,
    JournalCollection,
    JournalHistory,
)
from issue.models import Issue
from collection.models import Collection
from proc.models import IssueProc, JournalProc
from pid_provider.models import PidProviderConfig
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent
from proc.exceptions import ProcBaseException


# Constantes específicas da Core API
try:
    DEFAULT_CORE_TIMEOUT = 15
    CORE_TIMEOUT = int(
        PidProviderConfig.objects.filter(timeout__isnull=False).first().timeout
        or DEFAULT_CORE_TIMEOUT
    )
except Exception as e:
    CORE_TIMEOUT = DEFAULT_CORE_TIMEOUT


# Exceções específicas da Core API
class FetchMultipleJournalsError(ProcBaseException):
    """Erro quando a API retorna múltiplos journals para uma consulta específica."""

    pass


class UnableToGetJournalDataFromCoreError(ProcBaseException):
    """Erro ao obter dados de journal da API Core."""

    pass


class FetchJournalDataException(ProcBaseException):
    """Erro genérico ao buscar dados de journal da API."""

    pass


class FetchIssueDataException(ProcBaseException):
    """Erro genérico ao buscar dados de issue da API."""

    pass


def create_or_update_journal(
    journal_title, issn_electronic, issn_print, user, force_update=None
):
    """
    Cria ou atualiza um journal baseado nos dados da API Core.

    Esta função é chamada no fluxo de ingresso de conteúdo novo.
    Para migração, use migration.controller.create_or_update_journal.
    """
    force_update = (
        force_update
        or not JournalProc.objects.filter(
            Q(journal__official_journal__issn_electronic=issn_electronic)
            | Q(journal__official_journal__issn_print=issn_print)
        ).exists()
    )

    if not force_update:
        try:
            return Journal.get_registered(journal_title, issn_electronic, issn_print)
        except Journal.DoesNotExist:
            pass

    try:
        fetch_and_create_journal(
            user,
            issn_electronic=issn_electronic,
            issn_print=issn_print,
            force_update=force_update,
        )
    except FetchMultipleJournalsError as exc:
        raise exc
    except FetchJournalDataException as exc:
        pass

    try:
        return Journal.get_registered(journal_title, issn_electronic, issn_print)
    except Journal.DoesNotExist as exc:
        return None


def fetch_and_create_journal(
    user,
    collection_acron=None,
    issn_electronic=None,
    issn_print=None,
    force_update=None,
):
    """
    Busca dados do journal na API Core e cria/atualiza as entidades correspondentes.
    Agora com suporte a paginação para processar todos os resultados.
    """
    # Conta os resultados primeiro para validação

    try:
        block_unregistered_collection = not collection_acron
        results = fetch_journal_data_with_pagination(
            collection_acron=collection_acron,
            issn_electronic=issn_electronic,
            issn_print=issn_print,
        )
    except FetchJournalDataException:
        if not collection_acron:
            raise

        # api ainda não está aceitando o param collection_acron,
        # consulta api com collection_acron=None e
        # block_unregistered_collection=True
        results = fetch_journal_data_with_pagination(
            issn_electronic=issn_electronic,
            issn_print=issn_print,
        )

    for result in results:
        try:
            process_journal_result(
                user, result, block_unregistered_collection, force_update
            )
        except Exception as e:
            logging.exception(e)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.source_core_api",
                    "username": user.username,
                    "collection": collection_acron,
                    "issn_electronic": issn_electronic,
                    "issn_print": issn_print,
                    "force_update": force_update,
                    "data": result
                },
            )    


def fetch_journal_data_with_pagination(
    collection_acron=None,
    issn_electronic=None,
    issn_print=None,
):
    """
    Busca dados do journal na API Core com suporte a paginação.
    Retorna um gerador que yield cada resultado individualmente.
    """
    # Parâmetros iniciais
    params = {
        "issn_print": issn_print,
        "issn_electronic": issn_electronic,
        "collection_acron": collection_acron,
    }
    params = {k: v for k, v in params.items() if v}

    url = settings.JOURNAL_API_URL
    while url:
        try:
            response = fetch_data(
                url=url,
                params=params,  # Params só na primeira requisição
                json=True,
                timeout=CORE_TIMEOUT,
            )
        except Exception as e:
            raise FetchJournalDataException(
                f"fetch_journal_data_with_pagination: {url} {params} {e}"
            )
        else:
            # Próxima URL (se existir)
            url = response.get("next")
            yield from response.get("results") or []


def process_journal_result(user, result, block_unregistered_collection, force_update=None):
    """
    Processa um único resultado de journal da API e cria/atualiza as entidades correspondentes.
    """

    if block_unregistered_collection:
        collections = []
        for item in result.get("scielo_journal") or []:
            collections.append(item["collection_acron"])
        if not collections:
            return
        if not Collection.objects.filter(acron__in=collections).exists():
            return

    # Processa dados oficiais do journal
    official = result["official"]
    official_journal = OfficialJournal.create_or_update(
        title=official.get("title"),
        title_iso=official.get("iso_short_title"),
        issn_print=official.get("issn_print"),
        issn_electronic=official.get("issn_electronic"),
        issnl=official.get("issnl"),
        foundation_year=official.get("foundation_year"),
        user=user,
    )
    official_journal.add_related_journal(
        result.get("previous_journal_title"),
        (result.get("next_journal_title") or {}).get("next_journal_title"),
    )

    # Cria/atualiza o journal
    journal = Journal.create_or_update(
        user=user,
        official_journal=official_journal,
        title=result.get("title"),
        short_title=result.get("short_title"),
    )

    # Atualiza campos adicionais do journal
    journal.license_code = (result.get("journal_use_license") or {}).get("license_type")
    journal.nlm_title = result.get("nlm_title")
    journal.doi_prefix = result.get("doi_prefix")
    journal.wos_areas = result["wos_areas"]
    journal.logo_url = result["url_logo"]
    journal.save()

    # Processa subjects
    for item in result.get("Subject") or []:
        journal.subjects.add(Subject.create_or_update(user, item["value"]))

    # Processa publishers
    for item in result.get("publisher") or []:
        institution = Institution.get_or_create(
            inst_name=item["name"],
            inst_acronym=None,
            level_1=None,
            level_2=None,
            level_3=None,
            location=None,
            user=user,
        )
        journal.publisher.add(Publisher.create_or_update(user, journal, institution))

    # Processa owners
    for item in result.get("owner") or []:
        institution = Institution.get_or_create(
            inst_name=item["name"],
            inst_acronym=None,
            level_1=None,
            level_2=None,
            level_3=None,
            location=None,
            user=user,
        )
        journal.owner.add(Owner.create_or_update(user, journal, institution))
    # Processa dados específicos do SciELO
    for item in result.get("scielo_journal") or []:
        try:
            collection = Collection.objects.get(acron=item["collection_acron"])
        except Collection.DoesNotExist:
            continue

        journal_proc = JournalProc.get_or_create(user, collection, item["issn_scielo"])
        journal_proc.update(
            user=user,
            journal=journal,
            acron=item["journal_acron"],
            title=journal.title,
            availability_status=item.get("availability_status") or "C",
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
            force_update=force_update,
        )
        if not journal.journal_acron:
            journal.journal_acron = item.get("journal_acron")
            journal.save()
        journal_collection = JournalCollection.create_or_update(
            user, collection, journal
        )

        # Processa histórico do journal
        for jh in item.get("journal_history") or []:
            JournalHistory.create_or_update(
                user,
                journal_collection,
                jh["event_type"],
                jh["year"],
                jh["month"],
                jh["day"],
                jh["interruption_reason"],
            )
    return journal


def create_or_update_issue(
    journal, pub_year, volume, suppl, number, user, force_update=None
):
    """
    Cria ou atualiza um issue baseado nos dados da API Core.

    Esta função é chamada no fluxo de ingresso de conteúdo novo.
    Para migração, use migration.controller.create_or_update_issue.
    """
    force_update = (
        force_update
        or not IssueProc.objects.filter(
            journal_proc__journal=journal,
            issue__publication_year=pub_year,
            issue__volume=volume,
            issue__number=number,
            issue__supplement=suppl,
        ).exists()
    )

    if not force_update:
        try:
            return Issue.get(
                journal=journal,
                volume=volume,
                supplement=suppl,
                number=number,
            )
        except Issue.DoesNotExist:
            pass

    try:
        fetch_and_create_issues(journal, pub_year, volume, suppl, number, user)
    except FetchIssueDataException as exc:
        pass

    try:
        return Issue.get(
            journal=journal,
            volume=volume,
            supplement=suppl,
            number=number,
        )
    except Issue.DoesNotExist as exc:
        return None


def fetch_and_create_issues(journal, pub_year, volume, suppl, number, user):
    """
    Busca dados de issues na API Core e cria/atualiza as entidades correspondentes.
    """
    if journal:
        issn_print = journal.official_journal.issn_print
        issn_electronic = journal.official_journal.issn_electronic
        try:
            params = {
                "issn_print": issn_print,
                "issn_electronic": issn_electronic,
                "volume": volume,
            }
            params = {k: v for k, v in params.items() if v}
            response = fetch_data(
                url=settings.ISSUE_API_URL,
                params=params,
                json=True,
                timeout=CORE_TIMEOUT,
            )

        except Exception as e:
            raise FetchIssueDataException(
                f"fetch_and_create_issue: {settings.ISSUE_API_URL} {params} {e}"
            )

        issue = None
        for result in response.get("results") or []:
            logging.info(f"fetch_and_create_issues {params}: {result}")
            issue = Issue.get_or_create(
                journal=journal,
                volume=result["volume"],
                supplement=result["supplement"],
                number=result["number"],
                publication_year=result["year"],
                user=user,
            )

            for journal_proc in JournalProc.objects.filter(journal=journal):
                try:
                    issue_proc = IssueProc.objects.get(
                        collection=journal_proc.collection, issue=issue
                    )
                except IssueProc.DoesNotExist:
                    issue_proc = IssueProc.create_from_journal_proc_and_issue(
                        user,
                        journal_proc,
                        issue,
                    )
