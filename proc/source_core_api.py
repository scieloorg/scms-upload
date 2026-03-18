"""
Módulo responsável pela busca e processamento de dados da API Core externa.
"""

import logging
import sys

from django.conf import settings
from django.db.models import Q

from collection.models import Collection
from core.utils.requester import fetch_data
from issue.models import Issue
from journal.models import (
    Institution,
    Journal,
    JournalCollection,
    JournalHistory,
    OfficialJournal,
    Owner,
    Publisher,
    Sponsor,
    Subject,
)
from pid_provider.models import PidProviderConfig
from proc.exceptions import ProcBaseException
from proc.models import IssueProc, JournalProc
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent

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


class JournalDataChecker:
    """Consulta e valida dados de journal usando dados locais e API do core."""

    def __init__(self, journal_title, issn_electronic, issn_print, user):
        self.journal_title = journal_title
        self.issn_electronic = issn_electronic
        self.issn_print = issn_print
        self._user = user
        self.core_communication_error = False

    @classmethod
    def from_xmltree(cls, xmltree, user):
        """Cria instância a partir de xmltree."""
        from packtools.sps.models.journal_meta import ISSN, Title

        xml = Title(xmltree)
        journal_title = xml.journal_title
        xml = ISSN(xmltree)
        issn_electronic = xml.epub
        issn_print = xml.ppub
        return cls(journal_title, issn_electronic, issn_print, user)

    def get_local(self):
        """Consulta dados locais de journal."""
        return Journal.get_registered(
            self.journal_title, self.issn_electronic, self.issn_print
        )

    def fetch_from_core(self, force_update=True):
        """Consulta dados remotos de journal e atualiza os dados locais."""
        self.core_communication_error = False
        try:
            fetch_and_create_journal(
                self._user,
                issn_electronic=self.issn_electronic,
                issn_print=self.issn_print,
                force_update=force_update,
            )
        except FetchJournalDataException as e:
            self.core_communication_error = True
            logging.warning(f"Core API communication failure for journal: {e}")

    def get_or_fetch(self):
        """Consulta dados locais; se inexistentes, consulta o core e tenta novamente."""
        # 1. consulta dados locais de journal
        try:
            return self.get_local()
        except Journal.DoesNotExist:
            pass

        # 2. dados locais inexistentes, consulta dados remotos de journal
        # e atualiza os dados locais com os dados remotos
        self.fetch_from_core()

        # 3. consulta dados locais novamente após a tentativa de busca remota
        try:
            return self.get_local()
        except Journal.DoesNotExist:
            return None

    def refresh(self, response):
        """Consulta dados remotos de journal e atualiza response."""
        self.fetch_from_core()
        if self.core_communication_error:
            response["core_communication_error"] = True
            return

        # consulta dados locais após a atualização remota
        try:
            response["journal"] = self.get_local()
        except Journal.DoesNotExist:
            pass

    @staticmethod
    def ensure_proc_exists(user, journal):
        """
        Verifica e garante a existência de JournalProc para o journal.

        Args:
            user: O usuário que executa a operação
            journal: O journal que deve ter um JournalProc

        Returns:
            True se JournalProc existe

        Raises:
            JournalProc.DoesNotExist: Se não foi possível criar JournalProc
        """
        if (
            journal.missing_fields
            or not JournalProc.objects.filter(
                journal=journal, acron__isnull=False
            ).exists()
        ):
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

    checker = JournalDataChecker(journal_title, issn_electronic, issn_print, user)

    if not force_update:
        try:
            return checker.get_local()
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
        return checker.get_local()
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
                    "data": result,
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
        "collection": collection_acron,
    }
    params = {k: v for k, v in params.items() if v}

    url = settings.JOURNAL_API_URL
    if not url:
        return []
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
            params = {}
            yield from response.get("results") or []


def process_journal_result(
    user, result, block_unregistered_collection, force_update=None
):
    """
    Processa um único resultado de journal da API e cria/atualiza as entidades correspondentes.
    """

    if block_unregistered_collection:
        collections = set()
        for item in result.get("scielo_journal") or []:
            collections.add(item["collection_acron"])
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
        result.get("next_journal_title"),
    )

    # Cria/atualiza o journal
    journal = Journal.create_or_update(
        user=user,
        official_journal=official_journal,
        title=result.get("title"),
        short_title=result.get("short_title"),
    )
    journal.core_synchronized = False
    journal.contact_address = result.get("contact_address")
    journal.contact_name = result.get("contact_name")
    # Atualiza campos adicionais do journal
    journal.license_code = result.get("journal_use_license")
    journal.nlm_title = result.get("nlm_title")
    journal.doi_prefix = result.get("doi_prefix")
    journal.wos_areas = result.get("wos_areas", [])
    journal.logo_url = result.get("url_logo")
    journal.submission_online_url = result.get("submission_online_url")
    journal.save()

    journal.journal_email.all().delete()
    for item in result.get("email"):
        journal.add_email(item)

    # Processa subjects
    for item in result.get("subject") or []:
        journal.subject.add(Subject.create_or_update(user, item["value"]))

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

    for item in result.get("sponsor") or []:
        institution = Institution.get_or_create(
            inst_name=item["name"],
            inst_acronym=None,
            level_1=None,
            level_2=None,
            level_3=None,
            location=None,
            user=user,
        )
        journal.sponsor.add(Sponsor.create_or_update(user, journal, institution))

    # Processa subject descriptors (novo campo da API)
    for item in result.get("subject_descriptor") or []:
        journal.subject.add(Subject.create_or_update(user, item["value"]))

    no_lang = []
    for item in result.get("mission"):
        if not item["language"]:
            no_lang.append(item["rich_text"])
            continue
        if no_lang:
            item["rich_text"] = "\n".join(no_lang) + "\n" + item["rich_text"]

        journal.add_mission(user, item["language"], item["rich_text"])
        no_lang = []

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
            availability_status=item.get("status") or "C",
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
            force_update=force_update,
        )
        if not journal.journal_acron:
            journal.journal_acron = item.get("journal_acron")

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
    journal.core_synchronized = True
    journal.save()

    # TODO: Campos da API não processados ainda:
    # - copyright (array)
    # - table_of_contents (array)
    # - location (object with city_name, state_name, country_name, etc.)
    # - text_language (array)
    # - title_in_database (array)
    # - crossmark_policy (array)
    # - acronym (root level field)
    # - other_titles

    return journal


class IssueDataChecker:
    """Consulta e valida dados de issue usando dados locais e API do core."""

    def __init__(self, journal, publication_year, volume, suppl, number, user):
        self._journal = journal
        self.publication_year = publication_year
        self.volume = volume
        self.suppl = suppl
        self.number = number
        self._user = user
        self.core_communication_error = False

    @classmethod
    def from_xmltree(cls, xmltree, user, journal):
        """Cria instância a partir de xmltree."""
        from packtools.sps.models.dates import ArticleDates
        from packtools.sps.models.front_articlemeta_issue import ArticleMetaIssue

        xml = ArticleDates(xmltree)
        try:
            publication_year = xml.collection_date["year"]
        except (TypeError, KeyError, ValueError):
            try:
                publication_year = xml.article_date["year"]
            except (TypeError, KeyError, ValueError):
                publication_year = None

        xml = ArticleMetaIssue(xmltree)
        return cls(journal, publication_year, xml.volume, xml.suppl, xml.number, user)

    def get_local(self):
        """Consulta dados locais de issue."""
        return Issue.get(
            journal=self._journal,
            volume=self.volume,
            supplement=self.suppl,
            number=self.number,
        )

    def fetch_from_core(self):
        """Consulta dados remotos de issue e atualiza os dados locais."""
        self.core_communication_error = False
        try:
            fetch_and_create_issues(
                self._journal,
                self.publication_year,
                self.volume,
                self.suppl,
                self.number,
                self._user,
            )
        except FetchIssueDataException as e:
            self.core_communication_error = True
            logging.warning(f"Core API communication failure for issue: {e}")

    def get_or_fetch(self):
        """Consulta dados locais; se inexistentes, consulta o core e tenta novamente."""
        # 1. consulta dados locais de issue
        try:
            return self.get_local()
        except Issue.DoesNotExist:
            pass

        # 2. dados locais inexistentes, consulta dados remotos de issue
        # e atualiza os dados locais com os dados remotos
        self.fetch_from_core()

        # 3. consulta dados locais novamente após a tentativa de busca remota
        try:
            return self.get_local()
        except Issue.DoesNotExist:
            return None

    def refresh(self, response):
        """Consulta dados remotos de issue e atualiza response."""
        self.fetch_from_core()
        if self.core_communication_error:
            response["core_communication_error"] = True
            return

        # consulta dados locais após a atualização remota
        try:
            response["issue"] = self.get_local()
        except Issue.DoesNotExist:
            pass

    @staticmethod
    def ensure_proc_exists(user, issue):
        """
        Verifica e garante a existência de IssueProc para o issue.

        Args:
            user: O usuário que executa a operação
            issue: O issue que deve ter um IssueProc

        Returns:
            True se IssueProc existe

        Raises:
            IssueProc.DoesNotExist: Se não foi possível criar IssueProc
        """
        if IssueProc.objects.filter(issue=issue).exists():
            return True

        create_or_update_issue(
            journal=issue.journal,
            pub_year=issue.publication_year,
            volume=issue.volume,
            suppl=issue.supplement,
            number=issue.number,
            user=user,
            force_update=True,
        )

        if IssueProc.objects.filter(issue=issue).exists():
            return True

        raise IssueProc.DoesNotExist(f"IssueProc does not exist: {issue}")


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

    checker = IssueDataChecker(journal, pub_year, volume, suppl, number, user)

    if not force_update:
        try:
            return checker.get_local()
        except Issue.DoesNotExist:
            pass

    try:
        fetch_and_create_issues(journal, pub_year, volume, suppl, number, user)
    except FetchIssueDataException as exc:
        logging.warning(f"Erro ao buscar dados de issue: {exc}")
        pass

    try:
        return checker.get_local()
    except Issue.DoesNotExist as exc:
        return None


def fetch_and_create_issues(journal, pub_year, volume, suppl, number, user):
    """
    Busca dados de issues na API Core e cria/atualiza as entidades correspondentes.
    Agora com suporte a paginação para processar todos os resultados.
    """
    if not settings.ISSUE_API_URL:
        return None
    if journal:
        issn_print = journal.official_journal.issn_print
        issn_electronic = journal.official_journal.issn_electronic

        # Processa issues com paginação
        for result in fetch_issue_data_with_pagination(
            issn_print=issn_print,
            issn_electronic=issn_electronic,
            volume=volume,
        ):
            try:
                process_issue_result(user, journal, result)
            except Exception as e:
                logging.exception(e)
                exc_type, exc_value, exc_traceback = sys.exc_info()
                UnexpectedEvent.create(
                    e=e,
                    exc_traceback=exc_traceback,
                    detail={
                        "task": "proc.source_core_api.fetch_and_create_issues",
                        "username": user.username,
                        "issn_print": issn_print,
                        "issn_electronic": issn_electronic,
                        "volume": volume,
                        "data": result,
                    },
                )


def fetch_issue_data_with_pagination(
    issn_print=None,
    issn_electronic=None,
    volume=None,
):
    """
    Busca dados de issues na API Core com suporte a paginação.
    Retorna um gerador que yield cada resultado individualmente.
    """
    # Parâmetros iniciais
    params = {
        "issn_print": issn_print,
        "issn_electronic": issn_electronic,
        "volume": volume,
    }
    params = {k: v for k, v in params.items() if v}

    url = settings.ISSUE_API_URL
    if not url:
        return []

    while url:
        try:
            response = fetch_data(
                url=url,
                params=params,  # Params só na primeira requisição
                json=True,
                timeout=CORE_TIMEOUT,
            )
        except Exception as e:
            raise FetchIssueDataException(
                f"fetch_issue_data_with_pagination: {url} {params} {e}"
            )
        else:
            # Próxima URL (se existir)
            url = response.get("next")
            params = {}
            yield from response.get("results") or []


def process_issue_result(user, journal, result):
    """
    Processa um único resultado de issue da API e cria/atualiza as entidades correspondentes.
    """
    logging.info(
        f"process_issue_result: {journal} {result.get('volume')} {result.get('number')} {result.get('supplement')}"
    )

    # Cria/atualiza o issue com todos os campos da API
    issue = Issue.get_or_create(
        journal=journal,
        volume=result.get("volume"),
        supplement=result.get("supplement"),
        number=result.get("number"),
        publication_year=result.get("year"),
        user=user,
        order=result.get("order"),
        issue_pid_suffix=result.get("issue_pid_suffix"),
    )

    # Atualiza campos adicionais do issue se disponíveis na API
    if hasattr(issue, "season") and result.get("season"):
        issue.season = result.get("season")
    if hasattr(issue, "month") and result.get("month"):
        issue.month = result.get("month")

    issue.save()

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

    # TODO: Processar campos adicionais da API de issues:
    # - legacy_issue (array) - PIDs legados
    # - sections (array) - seções do issue
    # - issue_titles (array) - títulos específicos
    # - bibliographic_strips (array) - strips bibliográficas
    # - license (array) - licenças específicas do issue


# TODO FUTURO - Campos da API de Issues não processados ainda:
# Os seguintes campos estão disponíveis na API de issues mas ainda não são processados:
#
# 1. legacy_issue: Array com PIDs legados para compatibilidade
#    Exemplo: [{"pid": "0044-596720230001", "collection": "scl"}]
#
# 2. sections: Array de seções do issue com códigos e textos multilíngue
#    Exemplo: [{"text": "Original Articles", "code": "AA670", "language": "en", ...}]
#
# 3. issue_titles: Array de títulos específicos do issue (se houver)
#
# 4. bibliographic_strips: Array de strips bibliográficas em diferentes idiomas
#    Exemplo: [{"text": "Acta Amaz., vol.53, no.1, Manaus, Jan./Mar., 2023", "language": "en"}]
#
# 5. license: Array de licenças específicas do issue (se diferentes do journal)
#
# Para implementar esses campos no futuro, será necessário:
# - Criar modelos para IssueSection, IssueBibliographicStrip, etc. ou
# - Adicionar campos JSON no modelo Issue para armazenar esses dados
# - Implementar processamento desses campos na função process_issue_result
