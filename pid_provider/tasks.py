import logging
import sys

from django.contrib.auth import get_user_model

from config import celery_app
from core.utils.harvesters import OPACHarvester
from pid_provider.models import XMLURL
from pid_provider.provider import PidProvider
from pid_provider.requester import PidRequester
from proc.models import ArticleProc
from tracker.models import UnexpectedEvent

User = get_user_model()


def _get_user(request, username=None, user_id=None):
    try:
        return User.objects.get(pk=request.user.id)
    except AttributeError:
        if user_id:
            return User.objects.get(pk=user_id)
        if username:
            return User.objects.get(username=username)


@celery_app.task(bind=True, name="provide_pid_for_file")
def provide_pid_for_file(
    self,
    username=None,
    file_path=None,
    is_published=None,
):
    user = _get_user(self.request, username=username)

    pid_provider = PidProvider()
    for resp in pid_provider.provide_pid_for_xml_zip(
        file_path, user, is_published=is_published
    ):
        logging.info(resp)
    # return response


@celery_app.task(bind=True)
def task_fix_pid_v2(
    self,
    username=None,
    user_id=None,
):
    for article_proc in ArticleProc.objects.filter(sps_pkg__isnull=False).iterator():
        subtask_fix_pid_v2.apply_async(
            kwargs=dict(
                username=username,
                user_id=user_id,
                article_proc_id=article_proc.id,
            )
        )


@celery_app.task(bind=True)
def subtask_fix_pid_v2(
    self,
    username=None,
    user_id=None,
    article_proc_id=None,
):
    user = _get_user(self.request, username=username, user_id=user_id)
    article_proc = ArticleProc.objects.get(pk=article_proc_id)
    article_proc.fix_pid_v2(user)


@celery_app.task(bind=True)
def task_load_records_from_counter_dict(
    self,
    username=None,
    user_id=None,
    collection_acron=None,
    from_date=None,
    until_date=None,
    limit=None,
    timeout=None,
    force_update=None,
    opac_domain=None,
    stop=None,
    journal_acron=None,
):
    """
    Coleta documentos de uma coleção via endpoint counter_dict do OPAC e
    enfileira task_load_record_from_xml_url para cada documento público.

    Utiliza OPACHarvester para percorrer a API do novo site SciELO. Documentos
    marcados como não públicos (is_public=False) são ignorados.

    Args:
        self: Instância da tarefa Celery.
        username (str, optional): Nome do usuário executando a tarefa.
        user_id (int, optional): ID do usuário executando a tarefa.
        collection_acron (str, optional): Acrônimo da coleção.
            Se None, usa "scl" (Brasil) como padrão.
        from_date (str, optional): Data inicial para coleta (formato ISO).
        until_date (str, optional): Data final para coleta (formato ISO).
        limit (int, optional): Número de documentos por página da API (padrão: 100).
        timeout (int, optional): Timeout em segundos para requisições HTTP (padrão: 5).
        force_update (bool, optional): Força atualização mesmo se o registro
            já existe.
        opac_domain (str, optional): Domínio do OPAC (padrão: "www.scielo.br").
        stop (int, optional): Quantidade máxima de subtarefas disparadas.
            Se None, processa todos os documentos disponíveis.
        journal_acron (str, optional): Acrônimo do periódico para filtrar
            a coleta (ex: "rsp").

    Side Effects:
        - Dispara task_load_record_from_xml_url para cada documento público.
        - Registra UnexpectedEvent em caso de erro.
    """
    count = 0
    invalid_items = []
    exceptions = []

    try:
        user = _get_user(self.request, username=username, user_id=user_id)

        # Define coleção padrão se não especificada (apenas Brasil)
        if not collection_acron:
            collection_acron = "scl"

        # Cria harvester do OPAC
        harvester = OPACHarvester(
            domain=opac_domain or "www.scielo.br",
            collection_acron=collection_acron,
            from_date=from_date,
            until_date=until_date,
            limit=limit or 100,
            timeout=timeout or 5,
            journal_acron=journal_acron,
        )

        # Itera sobre documentos e dispara tarefas individuais
        for pid_v3, item in harvester.harvest_documents():
            try:
                document = harvester.format_raw(pid_v3, item)

                url = document.get("url")
                origin_date = document.get("origin_date")
                if not document.get("is_public"):
                    continue

                document_item = document.get("item") or {}

                task_load_record_from_xml_url.delay(
                    username=username,
                    user_id=user_id,
                    collection_acron=collection_acron,
                    pid_v3=pid_v3,
                    xml_url=url,
                    origin_date=origin_date,
                    force_update=force_update,
                    document_item=document_item,
                )
                if stop:
                    count += 1
                    if count >= stop:
                        break
            except Exception as e:
                exceptions.append({"error": str(e), "type": str(type(e))})
        if exceptions or invalid_items:
            raise ValueError(f"There are exceptions or invalid items")
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "task_load_records_from_counter_dict",
                "collection_acron": collection_acron,
                "from_date": from_date,
                "until_date": until_date,
                "limit": limit,
                "timeout": timeout,
                "force_update": force_update,
                "exceptions": exceptions,
                "invalid_items": invalid_items,
            },
        )


@celery_app.task(bind=True)
def task_load_record_from_xml_url(
    self,
    username=None,
    user_id=None,
    collection_acron=None,
    pid_v3=None,
    xml_url=None,
    origin_date=None,
    force_update=None,
    document_item=None,
):
    """
    Carrega um registro individual em PidProviderXML a partir de uma URL de XML.

    Esta tarefa baixa o XML do site SciELO e cria/atualiza registros apenas em
    PidProviderXML via PidProvider.provide_pid_for_xml_uri. Não cria registros
    de Article.

    Args:
        self: Instância da tarefa Celery.
        username (str, optional): Nome do usuário executando a tarefa.
        user_id (int, optional): ID do usuário executando a tarefa.
        collection_acron (str): Acrônimo da coleção (ex: "scl").
        pid_v3 (str): Identificador PID v3 do documento.
        xml_url (str): URL do XML do documento.
            Ex: "https://www.scielo.br/j/{journal}/a/{pid_v3}/?format=xml"
        origin_date (str, optional): Data de última atualização na fonte (formato ISO).
        force_update (bool, optional): Força reprocessamento mesmo se o registro
            já existe.
        document_item (dict, optional): Dados complementares do documento
            provenientes do OPAC (ex: metadados retornados pelo harvester).
            Armazenado no campo ``detail`` do XMLURL.

    Side Effects:
        - Cria ou atualiza um registro em PidProviderXML.
        - Registra UnexpectedEvent em caso de erro.
    """
    try:
        pid_provider = None
        user = _get_user(self.request, username=username, user_id=user_id)

        # Usa PidProvider para processar XML e criar registro em PidProviderXML
        pid_provider = PidProvider()
        
        # provide_pid_for_xml_uri cria/atualiza PidProviderXML mas não cria Article
        result = pid_provider.provide_pid_for_xml_uri(
            xml_uri=xml_url,
            name=f"{collection_acron}_{pid_v3}",
            user=user,
            origin_date=origin_date,
            force_update=force_update,
            is_published=None,
            registered_in_core=False,
            auto_solve_pid_conflict=False,
            document_item=document_item,
        )

        if result.get("error_msg"):
            logging.error(
                f"Error loading record {pid_v3}: {result.get('error_msg')}"
            )
        else:
            logging.info(
                f"Successfully loaded record {pid_v3} - "
                f"v3={result.get('v3')}, created={result.get('created')}"
            )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "task_load_record_from_xml_url",
                "collection_acron": collection_acron,
                "pid_v3": pid_v3,
                "xml_url": xml_url,
                "origin_date": origin_date,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_retry_xml_urls_by_status(
    self,
    username=None,
    user_id=None,
    collection_acron=None,
    status_list=None,
    force_update=None,
    stop=None,
    is_public=None,
    journal_acron=None,
):
    """
    Reprocessa registros XMLURL filtrando por status e enfileira
    task_load_record_from_xml_url para cada um.

    Args:
        self: Instância da tarefa Celery.
        username (str, optional): Nome do usuário executando a tarefa.
        user_id (int, optional): ID do usuário executando a tarefa.
        collection_acron (str, optional): Acrônimo da coleção repassado a cada
            subtarefa (ex: "scl"). Não é armazenado em XMLURL; deve ser
            fornecido explicitamente quando necessário.
        status_list (list[str], optional): Lista de status a filtrar
            (ex: ["failed", "error", "pending"]).
            Se None ou vazia, processa todos os registros independentemente
            do status.
        force_update (bool, optional): Força reprocessamento mesmo se o registro
            já existe.
        stop (int, optional): Quantidade máxima de subtarefas disparadas.
            Se None, processa todos os registros que correspondem ao filtro.
        is_public (bool, optional): Filtra registros pelo campo is_public.
            True → apenas documentos públicos; False → apenas não públicos;
            None → sem filtro.
        journal_acron (str, optional): Acrônimo do periódico para filtrar
            registros cujo URL contenha "/{journal_acron}/" (ex: "rsp").

    Side Effects:
        - Dispara task_load_record_from_xml_url para cada XMLURL encontrado.
        - Registra UnexpectedEvent em caso de erro.
    """
    exceptions = []
    count = 0

    try:
        params = {}
        if status_list:
            params["status__in"] = status_list
        if is_public is not None:
            # is_public pode ser None em registros antigos; por isso, ao filtrar, None é incluído na consulta para evitar exclusão inadvertida desses registros.
            params["is_public__in"] = (is_public, None)
        if journal_acron is not None:
            params["url__contains"] = f"/{journal_acron}/"

        qs = XMLURL.objects.filter(**params)

        for xmlurl in qs.iterator():
            try:
                document_item = None
                if xmlurl.detail:
                    document_item = xmlurl.detail.get("item")

                task_load_record_from_xml_url.delay(
                    username=username,
                    user_id=user_id,
                    collection_acron=collection_acron,
                    pid_v3=xmlurl.pid,
                    xml_url=xmlurl.url,
                    force_update=force_update,
                    document_item=document_item,
                )
                if stop:
                    count += 1
                    if count >= stop:
                        break
            except Exception as e:
                exceptions.append({"error": str(e), "type": str(type(e))})

        if exceptions:
            raise ValueError("There are exceptions")
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "task_retry_xml_urls_by_status",
                "collection_acron": collection_acron,
                "status_list": status_list,
                "force_update": force_update,
                "exceptions": exceptions,
            },
        )

