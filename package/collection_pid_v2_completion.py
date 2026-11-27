"""
Vínculo dos SPSPkg e Article anteriores à separação por coleção ao documento
na coleção (CollectionPidV2).

As funções recebem o registro de modelos (`apps`) para funcionar:
  - na migração de banco de dados, com os modelos históricos
    (article/migrations/0014_complete_collection_pid_v2.py)
  - na aplicação, com django.apps.apps (métodos dos modelos e a tarefa
    article.tasks.task_complete_collection_pid_v2)

Por isso usam somente campos e o manager padrão dos modelos, nunca métodos
ou propriedades. Ao alterar este módulo, usar somente campos que existem no
estado das migrações acima.

Somente vincula se não houver ambiguidade. Resultados:
  "linked", "already_linked", "no_ppx", "no_collection", "taken"
  (o documento na coleção já tem outro registro) e "error".

É idempotente: processar de novo só vincula o que ainda falta.

Preserva os campos legados (SPSPkg: ppx, pid_v3, pid_v2; Article: pp_xml,
pid_v2, sps_pkg): somente os vazios são completados com os dados do
documento na coleção, exceto se sync_fields=True (caminhos de escrita da
aplicação, ex.: SPSPkg.add_ppx). Para obter os dados do documento na
coleção, preferir collection_pid_v2 (ex.: SPSPkg.get_pid_v2).
"""

import logging
import time

from django.db import IntegrityError, transaction

LINKED = "linked"
ALREADY_LINKED = "already_linked"
NO_PPX = "no_ppx"
NO_COLLECTION = "no_collection"
TAKEN = "taken"
ERROR = "error"

# SPSPkg antes de Article: o Article é vinculado ao documento na coleção do
# seu pacote
MODEL_NAMES = ("SPSPkg", "Article")
MODELS = {
    "SPSPkg": ("package", "SPSPkg"),
    "Article": ("article", "Article"),
}

SPS_PKG_LINK_FIELDS = ["collection_pid_v2", "ppx", "pid_v3", "pid_v2"]
ARTICLE_LINK_FIELDS = ["collection_pid_v2", "pp_xml", "pid_v2", "sps_pkg"]


def get_model(apps, model_name):
    return apps.get_model(*MODELS[model_name])


def get_unique_ppx_id(apps, ppx_id, pid_v3):
    """
    PidProviderXML: o informado ou, na falta, o único do pid_v3
    """
    if ppx_id:
        return ppx_id
    if pid_v3:
        PidProviderXML = apps.get_model("pid_provider", "PidProviderXML")
        ids = list(
            PidProviderXML.objects.filter(v3=pid_v3).values_list("id", flat=True)[:2]
        )
        if len(ids) == 1:
            return ids[0]
    return None


def get_unique_collection_ids(queryset):
    """
    Até 2 coleções distintas do queryset (a ordenação padrão do modelo não
    pode entrar no DISTINCT)
    """
    return set(
        queryset.filter(collection__isnull=False)
        .order_by()
        .values_list("collection_id", flat=True)
        .distinct()[:2]
    )


def get_article_proc_of_unique_collection(apps, sps_pkg):
    """
    ArticleProc do pacote se todos os ArticleProc que o referenciam (ou,
    na falta, os do seu pid v2) são da mesma coleção; senão, None
    (não arrisca vincular o pacote à coleção errada)
    """
    ArticleProc = apps.get_model("proc", "ArticleProc")
    criteria = [ArticleProc.objects.filter(sps_pkg_id=sps_pkg.id)]
    if sps_pkg.pid_v2:
        criteria.append(ArticleProc.objects.filter(pid=sps_pkg.pid_v2))
    for queryset in criteria:
        collections = get_unique_collection_ids(queryset)
        if len(collections) > 1:
            return None
        if collections:
            return (
                queryset.filter(collection_id=collections.pop())
                .select_related("collection", "issue_proc__journal_proc")
                .order_by("-updated")
                .first()
            )
    return None


def get_or_create_collection_pid_v2(
    apps, user_id, ppx_id, collection_id, pid_v2=None, journal_acron=None
):
    """
    Obtém ou cria o documento na coleção; não altera o existente
    """
    CollectionPidV2 = apps.get_model("pid_provider", "CollectionPidV2")
    params = dict(pid_provider_xml_id=ppx_id, collection_id=collection_id)
    try:
        return CollectionPidV2.objects.get(**params)
    except CollectionPidV2.DoesNotExist:
        try:
            with transaction.atomic():
                return CollectionPidV2.objects.create(
                    creator_id=user_id,
                    pid_v2=pid_v2,
                    journal_acron=journal_acron,
                    **params,
                )
        except IntegrityError:
            return CollectionPidV2.objects.get(**params)


def _user_id(user_id, obj):
    return user_id or obj.updated_by_id or obj.creator_id


def _is_taken(model, collection_pid_v2, obj):
    return (
        model.objects.filter(collection_pid_v2_id=collection_pid_v2.id)
        .exclude(id=obj.id)
        .exists()
    )


def _update_link(model, obj, link_fields, values):
    """
    Grava o vínculo somente se o registro ainda não está vinculado
    (trava otimista contra processos concorrentes)

    Retorna LINKED, ALREADY_LINKED ou TAKEN
    """
    try:
        with transaction.atomic():
            updated = model.objects.filter(
                id=obj.id, collection_pid_v2__isnull=True
            ).update(**values)
    except IntegrityError:
        # outro processo vinculou outro registro ao documento na coleção
        obj.refresh_from_db(fields=link_fields)
        return TAKEN
    if not updated:
        # outro processo vinculou este registro
        obj.refresh_from_db(fields=link_fields)
        return ALREADY_LINKED
    return LINKED


def _link_values(obj, collection_pid_v2, values, sync_fields):
    """
    Valores a gravar no vínculo: collection_pid_v2 e, dos demais campos,
    somente os vazios (ou todos, se sync_fields)
    """
    result = {"collection_pid_v2": collection_pid_v2}
    for name, value in values.items():
        if value and (sync_fields or not getattr(obj, name)):
            result[name] = value
    return result


def link_sps_pkg(apps, sps_pkg, user_id=None, sync_fields=False):
    """
    Vincula ao documento na coleção (collection_pid_v2) o pacote anterior à
    separação por coleção, somente se não houver ambiguidade:
      - PidProviderXML: ppx ou o único do pid_v3
      - coleção: a única dos ArticleProc do pacote (ou do pid v2)
      - o documento na coleção ainda não tem pacote (OneToOne)

    Atualiza sps_pkg (instância) com os dados do vínculo
    """
    if sps_pkg.collection_pid_v2_id:
        return ALREADY_LINKED

    ppx_id = get_unique_ppx_id(apps, sps_pkg.ppx_id, sps_pkg.pid_v3)
    if not ppx_id:
        return NO_PPX

    article_proc = get_article_proc_of_unique_collection(apps, sps_pkg)
    if not article_proc:
        return NO_COLLECTION

    journal_proc = article_proc.issue_proc and article_proc.issue_proc.journal_proc
    collection_pid_v2 = get_or_create_collection_pid_v2(
        apps,
        _user_id(user_id, sps_pkg),
        ppx_id,
        article_proc.collection_id,
        pid_v2=sps_pkg.pid_v2 or article_proc.pid,
        journal_acron=journal_proc and journal_proc.acron,
    )
    model = type(sps_pkg)
    if _is_taken(model, collection_pid_v2, sps_pkg):
        return TAKEN

    PidProviderXML = apps.get_model("pid_provider", "PidProviderXML")
    v3 = (
        PidProviderXML.objects.filter(id=ppx_id).values_list("v3", flat=True).first()
    )
    values = _link_values(
        sps_pkg,
        collection_pid_v2,
        dict(ppx_id=ppx_id, pid_v3=v3, pid_v2=collection_pid_v2.pid_v2),
        sync_fields,
    )
    result = _update_link(model, sps_pkg, SPS_PKG_LINK_FIELDS, values)
    if result != LINKED:
        return result
    for name, value in values.items():
        setattr(sps_pkg, name, value)

    if sps_pkg.sps_pkg_name and not collection_pid_v2.sps_pkg_name:
        collection_pid_v2.sps_pkg_name = sps_pkg.sps_pkg_name
        collection_pid_v2.save(update_fields=["sps_pkg_name"])
    return LINKED


def get_article_collection_pid_v2_without_sps_pkg(apps, article, user_id=None):
    """
    Documento na coleção do artigo sem pacote, se não houver ambiguidade:
    PidProviderXML (pp_xml ou o único do pid_v3) e coleção (a única dos
    ArticleProc do pid v2 ou, na falta, a única coleção do periódico)

    Retorna (collection_pid_v2, None) ou (None, motivo)
    """
    ArticleProc = apps.get_model("proc", "ArticleProc")
    JournalProc = apps.get_model("proc", "JournalProc")

    ppx_id = get_unique_ppx_id(apps, article.pp_xml_id, article.pid_v3)
    if not ppx_id:
        return None, NO_PPX

    collections = set()
    if article.pid_v2:
        collections = get_unique_collection_ids(
            ArticleProc.objects.filter(pid=article.pid_v2)
        )
    if not collections and article.journal_id:
        collections = get_unique_collection_ids(
            JournalProc.objects.filter(journal_id=article.journal_id)
        )
    if len(collections) != 1:
        return None, NO_COLLECTION
    collection_id = collections.pop()

    journal_acron = article.journal_id and (
        JournalProc.objects.filter(
            journal_id=article.journal_id, collection_id=collection_id
        )
        .values_list("acron", flat=True)
        .first()
    )
    collection_pid_v2 = get_or_create_collection_pid_v2(
        apps,
        _user_id(user_id, article),
        ppx_id,
        collection_id,
        pid_v2=article.pid_v2,
        journal_acron=journal_acron or None,
    )
    return collection_pid_v2, None


def complete_journal_acron(apps, article, collection_pid_v2):
    """
    Completa o acrônimo do periódico no documento na coleção com o do
    periódico do artigo na coleção (JournalProc)
    """
    if collection_pid_v2.journal_acron or not article.journal_id:
        return
    JournalProc = apps.get_model("proc", "JournalProc")
    journal_acron = (
        JournalProc.objects.filter(
            journal_id=article.journal_id,
            collection_id=collection_pid_v2.collection_id,
        )
        .exclude(acron__isnull=True)
        .values_list("acron", flat=True)
        .first()
    )
    if journal_acron:
        collection_pid_v2.journal_acron = journal_acron
        collection_pid_v2.save(update_fields=["journal_acron"])


def link_article(apps, article, user_id=None, sync_fields=False):
    """
    Vincula ao documento na coleção (collection_pid_v2) o artigo anterior à
    separação por coleção, somente se não houver ambiguidade:
      - com pacote: o documento na coleção do pacote (o pacote é vinculado
        antes, se necessário)
      - sem pacote: ver get_article_collection_pid_v2_without_sps_pkg
      - o documento na coleção ainda não tem artigo (OneToOne)

    Atualiza article (instância) com os dados do vínculo
    """
    if article.collection_pid_v2_id:
        return ALREADY_LINKED

    if article.sps_pkg_id:
        sps_pkg = article.sps_pkg
        result = link_sps_pkg(apps, sps_pkg, user_id, sync_fields)
        if not sps_pkg.collection_pid_v2_id:
            # pacote com coleção ambígua ou vinculado a outro documento
            return NO_COLLECTION if result == TAKEN else result
        collection_pid_v2 = sps_pkg.collection_pid_v2
    else:
        collection_pid_v2, result = get_article_collection_pid_v2_without_sps_pkg(
            apps, article, user_id
        )
        if not collection_pid_v2:
            return result

    model = type(article)
    if _is_taken(model, collection_pid_v2, article):
        return TAKEN

    SPSPkg = get_model(apps, "SPSPkg")
    sps_pkg_id = (
        SPSPkg.objects.filter(collection_pid_v2_id=collection_pid_v2.id)
        .values_list("id", flat=True)
        .first()
    )
    values = _link_values(
        article,
        collection_pid_v2,
        dict(
            pp_xml_id=collection_pid_v2.pid_provider_xml_id,
            pid_v2=collection_pid_v2.pid_v2,
            sps_pkg_id=sps_pkg_id,
        ),
        sync_fields,
    )
    result = _update_link(model, article, ARTICLE_LINK_FIELDS, values)
    if result != LINKED:
        return result
    for name, value in values.items():
        setattr(article, name, value)

    complete_journal_acron(apps, article, collection_pid_v2)
    return LINKED


LINK_FUNCTIONS = {"SPSPkg": link_sps_pkg, "Article": link_article}


def complete_batch(apps, model_name, user_id=None, last_id=0, batch_size=100):
    """
    Vincula um lote de registros (model_name) ainda não vinculados, com
    id > last_id, em ordem de id.

    O cursor (last_id) avança inclusive nos registros que não puderam ser
    vinculados (ambíguos), para que não sejam reprocessados a cada lote.

    Retorna (stats, last_id, done)
    """
    model = get_model(apps, model_name)
    link = LINK_FUNCTIONS[model_name]
    ids = list(
        model.objects.filter(id__gt=last_id, collection_pid_v2__isnull=True)
        .order_by("id")
        .values_list("id", flat=True)[:batch_size]
    )
    stats = {}
    for obj in model.objects.filter(id__in=ids).order_by("id"):
        try:
            result = link(apps, obj, user_id)
        except Exception as e:
            logging.exception(e)
            result = ERROR
        stats[result] = stats.get(result, 0) + 1
    return stats, (ids[-1] if ids else last_id), len(ids) < batch_size


def complete(
    apps,
    user_id=None,
    model_name=MODEL_NAMES[0],
    last_id=0,
    batch_size=500,
    max_seconds=None,
):
    """
    Vincula, lote a lote, todos os SPSPkg e depois todos os Article ainda
    não vinculados, a partir de (model_name, last_id).

    max_seconds: interrompe ao ultrapassar o tempo (None: até terminar);
    o restante pode ser executado depois a partir de (model_name, last_id)
    retornados, ex.: pela tarefa article.tasks.task_complete_collection_pid_v2

    Retorna {"model_name", "last_id", "done", "stats": {model_name: stats}}
    """
    started = time.monotonic()
    stats = {}
    index = MODEL_NAMES.index(model_name)
    while True:
        batch_stats, last_id, done = complete_batch(
            apps, model_name, user_id, last_id, batch_size
        )
        model_stats = stats.setdefault(model_name, {})
        for key, value in batch_stats.items():
            model_stats[key] = model_stats.get(key, 0) + value
        if done:
            index += 1
            if index >= len(MODEL_NAMES):
                return {
                    "model_name": model_name,
                    "last_id": last_id,
                    "done": True,
                    "stats": stats,
                }
            model_name = MODEL_NAMES[index]
            last_id = 0
        if max_seconds is not None and time.monotonic() - started > max_seconds:
            return {
                "model_name": model_name,
                "last_id": last_id,
                "done": False,
                "stats": stats,
            }


def count_unlinked(apps):
    """
    Quantidade de registros sem vínculo ao documento na coleção, por modelo.
    Ao final do processamento completo, são os ambíguos (tratamento manual)
    """
    return {
        model_name: get_model(apps, model_name)
        .objects.filter(collection_pid_v2__isnull=True)
        .count()
        for model_name in MODEL_NAMES
    }
