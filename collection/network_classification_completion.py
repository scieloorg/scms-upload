"""
Preenchimento de Collection.network_classification a partir do articlemeta.

Usado pela migração collection 0007_complete_network_classification
(modelos históricos), por Collection.complete_network_classification e
pela tarefa collection.tasks.task_complete_network_classification.

Recebe `apps` (django.apps.apps ou o registro histórico da migração) e usa
somente campos do modelo, para funcionar com modelos históricos.

Na falta do dado no articlemeta (indisponível ou sem a coleção), a
classificação é inferida pelo nome da coleção (ver
infer_network_classification):
  - SciELO Saúde Pública: scielonetwork e thematic
  - SciELO com nome de país (ex.: SciELO Brasil): scielonetwork
  - demais (ex.: Pepsic): thematic
"""

import logging
import re
import unicodedata

from django.db.models import Q
from django.utils import timezone

from core.utils.requester import fetch_data

ARTICLEMETA_COLLECTIONS_URL = (
    "https://articlemeta.scielo.org/api/v1/collection/identifiers/"
)

SCIELONETWORK = "scielonetwork"
THEMATIC = "thematic"

PUBLIC_HEALTH_NAMES = {"saude publica", "salud publica", "public health"}

# nomes de países (pt, es, en), sem acentos e em minúsculas
COUNTRY_NAMES = {
    "africa do sul", "south africa", "sudafrica",
    "angola",
    "argentina",
    "bolivia",
    "brasil", "brazil",
    "cabo verde", "cape verde",
    "chile",
    "colombia",
    "costa rica",
    "cuba",
    "ecuador", "equador",
    "el salvador",
    "espana", "espanha", "spain",
    "guatemala",
    "honduras",
    "mexico",
    "mocambique", "mozambique",
    "nicaragua",
    "panama",
    "paraguay", "paraguai",
    "peru",
    "portugal",
    "puerto rico", "porto rico",
    "republica dominicana", "dominican republic",
    "uruguay", "uruguai",
    "venezuela",
}


def normalize_network_classification(network_classification):
    """
    Retorna network_classification como lista ou None
    Ex.: "scielonetwork" -> ["scielonetwork"]
    """
    if isinstance(network_classification, str):
        network_classification = [network_classification]
    return [item for item in network_classification or [] if item] or None


def _normalize_name(name):
    """
    Sem acentos, em minúsculas, sem pontuação e sem o prefixo "SciELO"
    Ex.: "SciELO Saúde Pública" -> "saude publica"
    """
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())
    if text.startswith("scielo "):
        text = text[len("scielo "):]
    return text


def infer_network_classification(name):
    """
    Infere network_classification pelo nome da coleção:
      - SciELO Saúde Pública: scielonetwork e thematic
      - SciELO com nome de país (ex.: SciELO Brasil): scielonetwork
      - demais (ex.: Pepsic): thematic
    Retorna None se a coleção não tem nome
    """
    text = _normalize_name(name)
    if not text:
        return None
    if text in PUBLIC_HEALTH_NAMES:
        return [SCIELONETWORK, THEMATIC]
    if text in COUNTRY_NAMES:
        return [SCIELONETWORK]
    return [THEMATIC]


def get_collections_without_network_classification(apps):
    Collection = apps.get_model("collection", "Collection")
    return Collection.objects.filter(
        Q(network_classification__isnull=True) | Q(network_classification=[])
    )


def complete(apps, user_id=None, collections_data=None, verify=False):
    """
    Preenche em lote network_classification das coleções que estão sem
    esse dado, a partir dos dados do articlemeta (collections_data ou,
    na falta, consultados em ARTICLEMETA_COLLECTIONS_URL). Na falta do
    dado no articlemeta (indisponível ou sem a coleção), infere pelo nome
    (ver infer_network_classification).
    Coleções já preenchidas não são alteradas.

    Retorna {"updated": [acron, ...], "inferred": [acron, ...],
    "not_found": [acron, ...]}; inferred é subconjunto de updated;
    not_found: sem dado no articlemeta e sem nome para inferir
    """
    Collection = apps.get_model("collection", "Collection")
    queryset = get_collections_without_network_classification(apps)
    result = {"updated": [], "inferred": [], "not_found": []}
    if not queryset.exists():
        return result

    if not collections_data:
        try:
            collections_data = fetch_data(
                ARTICLEMETA_COLLECTIONS_URL,
                json=True,
                verify=verify,
            )
        except Exception as e:
            # infere todas pelo nome
            logging.exception(f"complete_network_classification: articlemeta: {e}")
            result["articlemeta_error"] = f"{type(e).__name__}: {e}"
            collections_data = []
    network_classification_by_acron = {
        item.get("acron"): normalize_network_classification(
            item.get("network_classification")
        )
        for item in collections_data or []
    }

    now = timezone.now()
    items = []
    for obj in queryset:
        network_classification = network_classification_by_acron.get(obj.acron)
        if not network_classification:
            network_classification = infer_network_classification(obj.name)
            if not network_classification:
                result["not_found"].append(obj.acron)
                continue
            result["inferred"].append(obj.acron)
        obj.network_classification = network_classification
        obj.updated_by_id = user_id
        # bulk_update não aplica auto_now
        obj.updated = now
        items.append(obj)
        result["updated"].append(obj.acron)

    Collection.objects.bulk_update(
        items, ["network_classification", "updated_by", "updated"]
    )
    logging.info(f"complete_network_classification: {result}")
    return result
