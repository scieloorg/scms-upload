"""
Relatório de qualidade da conversão HTML -> XML, agrupado por categoria.

Análogo ao relatório de problemas (``proc.problem_report``), mas voltado à
conversão feita por ``HTMLXML.html_to_xml`` (biblioteca
``scielo_classic_website``): o objetivo é separar **problemas sistemáticos**
(bugs do conversor, que se repetem em muitos periódicos) de **problemas de
dados** (HTML particular de um periódico/fascículo) e priorizar a correção
pela frequência.

Analisa todos os artigos convertidos do escopo (não só os BLOCKED/PENDING:
uma conversão "DONE" pode ter perdido conteúdo). Para cada artigo levanta
"achados", cada um com uma verificação (``check``) e uma chave (ex.: o nome
da tag, o passo que falhou com a exceção e o ponto do código). A categoria é
o par (verificação, chave); categorias são ordenadas por quantidade de
artigos (C001 = mais frequente).

Fontes, da mais barata para a mais cara:

1. **falhas** (evento ``html_to_xml`` em ``ArticleProcResult``): passo da
   conversão que levantou exceção (o 1º é a causa; os seguintes, em geral,
   consequência), exceções registradas pela biblioteca, conversão
   interrompida, erro ao gerar o relatório/ZIP;
2. **conteúdo** (contadores já gravados em ``HTMLXML``): body vazio,
   referências perdidas, traduções ausentes, ``article-type`` fora do JATS,
   menos imagens/tabelas no XML que no HTML;
3. **estrutura do XML gerado** (lê o arquivo): elementos que não são JATS
   (HTML que sobrou), ``xref`` apontando para ``id`` inexistente,
   ``ref-type`` inválido, ``id`` duplicado, ``table-wrap``/``fig`` sem
   conteúdo;
4. **HTML sem correspondente no XML** (lê o HTML inicial e o XML): links,
   âncoras e imagens do HTML que não foram encontrados no XML, agrupados por
   padrão (ex.: ``a[href=#…]``, ``a[name=tN]``, ``img[src=journal-dir]``);
5. **texto perdido**: trechos do texto principal do HTML ausentes no XML,
   agrupados pela marcação em volta (ex.: ``span[sup] → text [after
   citation number]``).

As verificações estão em ``htmlxml.analysis`` (as mesmas do relatório de
cada conversão) e têm gravidade (crítico, importante, menor, informação);
as categorias são ordenadas pela gravidade e, em cada uma, pela frequência.

A "abrangência" de cada categoria (quantos periódicos, quanto o periódico
mais afetado concentra) ajuda a distinguir: difusa -> provável sistemático;
concentrada num periódico -> provável dado.

O resultado é um ZIP com CSVs (ver ``proc.problem_report.write_zip``), no
idioma de quem solicitou.
"""

import hashlib
import json
import logging
import tempfile
import time
import zipfile
from collections import Counter

from django.db.models import Count
from django.utils import timezone
from lxml import etree

from htmlxml import analysis as an
from htmlxml.analysis import (  # noqa: F401 (reexportados)
    CHECKS,
    GROUP_CONTENT,
    GROUP_FAILURE,
    GROUP_HTML,
    GROUP_STRUCTURE,
    GROUPS,
    NATURE_BUG,
    NATURE_CHECK,
    NATURE_DATA,
    NATURE_MAPPING,
    NATURES,
    STATUS_PROBLEM,
    STATUS_WITH_XML,
    _int,
    _text,
    a_href_pattern,
    a_name_pattern,
    code_location,
    content_findings,
    exception_signature,
    failure_findings,
    finding,
    html_findings,
    src_pattern,
    structure_findings,
)
from proc import problem_report as pr

ITEM_TYPE = "article"
EVENT_NAME = "html_to_xml"

# ---------------------------------------------------------------------------
# Análise de um artigo
# ---------------------------------------------------------------------------

HTMLXML_PREFIX = "migrated_data__htmlxml__"
HTMLXML_FIELDS = [
    "id",
    "updated",
    "html2xml_status",
    "quality",
    "file",
    "bb_init_file",
    "empty_body",
    "n_paragraphs",
    "n_references",
    "html_translation_langs",
    "article_type",
    "html_img_total",
    "html_table_total",
    "xml_graphic_total",
    "xml_inline_graphic_total",
    "xml_table_wrap_total",
    "xml_ref_elem_citation_total",
    "xml_ref_mixed_citation_total",
    "xml_text_lang_total",
]
PROC_FIELDS = [
    "id",
    "pid",
    "pkg_name",
    "xml_status",
    "collection__acron",
    "issue_proc__journal_proc__acron",
    "issue_proc__issue_folder",
]


def _parse(storage, name):
    if not name:
        raise FileNotFoundError("(no file)")
    with storage.open(name, "rb") as fp:
        return etree.parse(fp, etree.XMLParser(huge_tree=True, recover=False)).getroot()


def analyze_article(data, event, storage):
    """
    ``data``: contadores de ``HTMLXML`` (sem o prefixo) + ``journal_acron``.
    ``event``: ``{"detail": ...}`` do último ``html_to_xml`` ou None.
    Retorna (achados, % de texto perdido ou None se não comparado).
    """
    status = data.get("html2xml_status")
    detail = event.get("detail") if event else None
    found = failure_findings(status, detail, has_event=event is not None)
    if status not in STATUS_WITH_XML:
        return found, None

    report_failed = isinstance(detail, dict) and detail.get("report_exceptions")
    if report_failed:
        # os contadores só são atualizados quando o relatório individual é
        # gerado: sem ele, não são confiáveis
        data = {k: v for k, v in data.items() if not k.startswith(("html_", "xml_", "empty_", "n_"))}

    try:
        xml = _parse(storage, data.get("file"))
    except Exception as e:
        found.append(finding("xml_unreadable", type(e).__name__, example=str(e)))
        return found, None

    try:
        html = _parse(storage, data.get("bb_init_file"))
    except Exception as e:
        html = None
        found.append(finding("initial_html_unreadable", type(e).__name__, example=str(e)))
    result = an.evaluate(html, xml, data, data.get("journal_acron") or "")
    found.extend(result["findings"])
    text = result["text"]
    return found, (text["percent"] if text and text["compared"] else None)


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------


def category_key(check, key):
    raw = f"{check}|{key}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def _scope_queryset(scope):
    from proc.models import ArticleProc

    base_scope = {k: v for k, v in (scope or {}).items() if k not in ("updated_from", "updated_to")}
    qs = ArticleProc.objects.filter(pr._scope_filters(ITEM_TYPE, base_scope)).filter(
        migrated_data__htmlxml__isnull=False
    )
    start, end = pr.updated_range(scope or {})
    if start:
        qs = qs.filter(**{f"{HTMLXML_PREFIX}updated__gte": start})
    if end:
        qs = qs.filter(**{f"{HTMLXML_PREFIX}updated__lt": end})
    return qs


def _htmlxml_admin_url(htmlxml_id):
    from django.conf import settings

    base = (getattr(settings, "WAGTAILADMIN_BASE_URL", "") or "").rstrip("/")
    return f"{base}/admin/snippets/htmlxml/htmlxml/edit/{htmlxml_id}/"


def collect(scope, deadline=None, max_items=None, memory_limit=None):
    """
    Analisa os artigos convertidos do escopo, dos convertidos mais
    recentemente para os mais antigos. Para (relatório incompleto) ao
    atingir ``deadline``, ``memory_limit``, ``max_items`` ou erro de banco,
    como ``proc.problem_report.collect_problems``.

    Retorna ``{"rows", "categories", "overview", "coverage", "partial"}``;
    cada row é um artigo analisado, com ``findings``.
    """
    from htmlxml.models import HTMLXML

    storage = HTMLXML.file.field.storage
    result = {
        "rows": [],
        "categories": {},
        "overview": [],
        "coverage": {ITEM_TYPE: {"total": 0, "processed": 0}},
        "partial": None,
    }
    rows = result["rows"]
    try:
        qs = _scope_queryset(scope)
        result["coverage"][ITEM_TYPE]["total"] = qs.count()
        result["overview"] = _overview(qs)
        values = PROC_FIELDS + [HTMLXML_PREFIX + f for f in HTMLXML_FIELDS]
        stream = (
            qs.values(*values)
            .order_by(f"-{HTMLXML_PREFIX}updated", "-id")
            .iterator(chunk_size=pr.CHUNK_SIZE)
        )
        for chunk in pr._iter_chunks(stream, pr.CHUNK_SIZE):
            if deadline is not None and time.monotonic() >= deadline:
                raise pr._Stop(pr.PARTIAL_TIME)
            if memory_limit is not None:
                used = pr.current_memory_mb()
                if used >= memory_limit:
                    raise pr._Stop(pr.PARTIAL_MEMORY, f"memory {used:.0f} MB >= {memory_limit:.0f} MB")
            if max_items is not None and len(rows) >= max_items:
                raise pr._Stop(pr.PARTIAL_ITEMS, f"max_items={max_items}")
            if max_items is not None:
                chunk = chunk[: max_items - len(rows)]
            _collect_chunk(chunk, rows, result["categories"], storage, deadline)
            result["coverage"][ITEM_TYPE]["processed"] += len(chunk)
        cov = result["coverage"][ITEM_TYPE]
        if max_items is not None and cov["processed"] < cov["total"]:
            raise pr._Stop(pr.PARTIAL_ITEMS, f"max_items={max_items}")
    except pr._Stop as stop:
        result["partial"] = {"reason": stop.reason, "detail": stop.detail}
    except pr._soft_time_limit_exception():
        result["partial"] = {"reason": pr.PARTIAL_TIME, "detail": ""}
    except Exception as e:
        logging.exception("html2xml report: collection interrupted")
        result["partial"] = {"reason": pr.PARTIAL_ERROR, "detail": f"{type(e).__name__}: {e}"[:500]}

    rows.sort(key=lambda r: (r["collection"], r["journal_acron"], r["issue_folder"], r["item"]))
    return result


def _overview(qs):
    items = []
    for item in (
        qs.values(f"{HTMLXML_PREFIX}html2xml_status", f"{HTMLXML_PREFIX}quality")
        .annotate(total=Count("id"))
        .order_by("-total")
    ):
        items.append({
            "html2xml_status": item[f"{HTMLXML_PREFIX}html2xml_status"],
            "quality": item[f"{HTMLXML_PREFIX}quality"],
            "total": item["total"],
        })
    return items


def _last_events(proc_ids):
    from proc.models import ArticleProcResult

    events = {}
    for event in (
        ArticleProcResult.objects.filter(proc_id__in=proc_ids, name=EVENT_NAME)
        .order_by("proc_id", "created", "id")
        .values("proc_id", "detail", "completed", "created")
        .iterator(chunk_size=pr.CHUNK_SIZE)
    ):
        events[event["proc_id"]] = event
    return events


def _collect_chunk(chunk, rows, categories, storage, deadline=None):
    events = _last_events([r["id"] for r in chunk])
    for row in chunk:
        if deadline is not None and time.monotonic() >= deadline:
            raise pr._Stop(pr.PARTIAL_TIME)
        data = {f: row[HTMLXML_PREFIX + f] for f in HTMLXML_FIELDS}
        data["journal_acron"] = row.get("issue_proc__journal_proc__acron") or ""
        try:
            found, text_lost = analyze_article(data, events.get(row["id"]), storage)
        except pr._soft_time_limit_exception():
            raise
        except Exception as e:
            found = [finding("xml_unreadable", f"(report) {type(e).__name__}", example=str(e))]
            text_lost = None
        rows.append(_build_row(row, data, found, categories, text_lost))


def _build_row(row, data, found, categories, text_lost=None):
    collection = row.get("collection__acron") or ""
    journal_acron = row.get("issue_proc__journal_proc__acron") or ""
    issue_folder = row.get("issue_proc__issue_folder") or ""
    compact = []
    for item in found:
        key = category_key(item["check"], item["key"])
        categories.setdefault(key, (pr._shared(item["check"]), pr._shared(item["key"])))
        compact.append({
            "category": pr._shared(key),
            "check": pr._shared(item["check"]),
            "key": pr._shared(item["key"]),
            "count": item["count"],
            "example": item["example"],
        })
    langs = [x for x in _text(data.get("html_translation_langs")).split("-") if x]
    return {
        "item": pr.item_name(ITEM_TYPE, collection, journal_acron, issue_folder, row.get("pid"), row.get("pkg_name")),
        "item_type": ITEM_TYPE,
        "collection": pr._shared(collection),
        "journal_acron": pr._shared(journal_acron),
        "issue_folder": pr._shared(issue_folder),
        "pid": row.get("pid") or "",
        "pkg_name": row.get("pkg_name") or "",
        "xml_status": pr._shared(row.get("xml_status") or ""),
        "html2xml_status": pr._shared(data.get("html2xml_status") or ""),
        "quality": pr._shared(data.get("quality") or ""),
        "converted_at": pr._iso(data.get("updated")),
        "article_type": pr._shared(data.get("article_type") or ""),
        "n_paragraphs": _int(data.get("n_paragraphs")),
        "n_references": _int(data.get("n_references")),
        "mixed_citation": _int(data.get("xml_ref_mixed_citation_total")),
        "element_citation": _int(data.get("xml_ref_elem_citation_total")),
        "html_tables": _int(data.get("html_table_total")),
        "table_wraps": _int(data.get("xml_table_wrap_total")),
        "html_images": _int(data.get("html_img_total")),
        "xml_graphics": _int(data.get("xml_graphic_total")) + _int(data.get("xml_inline_graphic_total")),
        "html_langs": len(langs) + 1,
        "xml_langs": _int(data.get("xml_text_lang_total")),
        "text_lost_percent": "" if text_lost is None else text_lost,
        "severity": an.max_severity(found),
        "attention": an.attention_points(found),
        "findings": compact,
        "admin_url": _htmlxml_admin_url(data["id"]) if data.get("id") else "",
    }


# ---------------------------------------------------------------------------
# Agregação
# ---------------------------------------------------------------------------


def spread_kind(total_journals, top_share):
    """Abrangência: ``single`` (1 periódico), ``concentrated`` ou ``spread``."""
    if total_journals <= 1:
        return "single"
    if top_share >= 0.8:
        return "concentrated"
    return "spread"


def summarize(rows, categories, examples_per_category=pr.EXAMPLES_PER_CATEGORY):
    """
    Agrupa os achados por categoria, ordenados por quantidade de artigos
    (C001 = mais frequente); grava ``category_code`` nos achados.
    """
    analyzed = len(rows)
    groups = {}
    for row in rows:
        journal = (row["collection"], row["journal_acron"])
        for item in row["findings"]:
            key = item["category"]
            group = groups.get(key)
            if group is None:
                check, check_key = categories[key]
                group = groups[key] = {
                    "category": key,
                    "check": check,
                    "key": check_key,
                    "articles": 0,
                    "occurrences": 0,
                    "journals": Counter(),
                    "issues": set(),
                    "collections": set(),
                    "examples": [],
                    "example": item["example"],
                }
            group["articles"] += 1
            group["occurrences"] += item["count"] or 0
            group["journals"][journal] += 1
            group["collections"].add(row["collection"])
            if row["issue_folder"]:
                group["issues"].add((row["collection"], row["journal_acron"], row["issue_folder"]))
            if not group["example"] and item["example"]:
                group["example"] = item["example"]
            if len(group["examples"]) < examples_per_category:
                group["examples"].append(row["item"])

    summary = []
    for group in groups.values():
        (top_collection, top_journal), top_total = group["journals"].most_common(1)[0]
        top_share = top_total / group["articles"] if group["articles"] else 0
        group_name, nature = CHECKS.get(group["check"], (GROUP_FAILURE, NATURE_CHECK))
        summary.append({
            "category": group["category"],
            "severity": an.severity(group["check"]),
            "group": group_name,
            "check": group["check"],
            "key": group["key"],
            "nature": nature,
            "total": group["articles"],
            "percent": round(group["articles"] * 100 / analyzed, 2) if analyzed else 0,
            "occurrences": group["occurrences"],
            "total_journals": len(group["journals"]),
            "total_issues": len(group["issues"]),
            "total_collections": len(group["collections"]),
            "top_journal": pr.item_name("journal", top_collection, top_journal, "", ""),
            "top_journal_share": round(top_share * 100),
            "spread": spread_kind(len(group["journals"]), top_share),
            "example": group["example"],
            "examples": " | ".join(group["examples"]),
        })
    # os mais graves primeiro; em cada gravidade, os mais frequentes
    summary.sort(key=lambda g: (
        an.severity_rank(g["severity"]), -g["total"], -g["total_journals"], g["check"], g["key"],
    ))
    codes = {}
    for i, group in enumerate(summary, start=1):
        group["code"] = codes[group["category"]] = f"C{i:03d}"
    for row in rows:
        for item in row["findings"]:
            item["category_code"] = codes[item["category"]]
        row["category_codes"] = " ".join(sorted({i["category_code"] for i in row["findings"]}))
        row["total_categories"] = len(row["findings"])
    return summary


def by_journal(rows, top=5):
    """Uma linha por periódico: artigos analisados, com achados e principais categorias."""
    journals = {}
    for row in rows:
        key = (row["collection"], row["journal_acron"])
        entry = journals.get(key)
        if entry is None:
            entry = journals[key] = {
                "collection": row["collection"],
                "journal_acron": row["journal_acron"],
                "analyzed": 0,
                "with_findings": 0,
                "categories": Counter(),
            }
        entry["analyzed"] += 1
        if row["findings"]:
            entry["with_findings"] += 1
        for item in row["findings"]:
            entry["categories"][item["category_code"]] += 1
    result = []
    for entry in journals.values():
        result.append({
            "collection": entry["collection"],
            "journal_acron": entry["journal_acron"],
            "analyzed": entry["analyzed"],
            "with_findings": entry["with_findings"],
            "percent": round(entry["with_findings"] * 100 / entry["analyzed"], 2) if entry["analyzed"] else 0,
            "top_categories": "; ".join(f"{c} ({n})" for c, n in sorted(
                entry["categories"].items(), key=lambda x: (-x[1], x[0])
            )[:top]),
        })
    result.sort(key=lambda r: (-r["with_findings"], r["collection"], r["journal_acron"]))
    return result


def finding_rows(rows):
    """Uma linha por (artigo, categoria) — gerador."""
    for row in rows:
        base = {k: row[k] for k in (
            "item", "collection", "journal_acron", "issue_folder", "pid",
            "pkg_name", "html2xml_status", "quality", "admin_url",
        )}
        for item in row["findings"]:
            group, nature = CHECKS.get(item["check"], (GROUP_FAILURE, NATURE_CHECK))
            yield {
                **base,
                "severity": an.severity(item["check"]),
                "category_code": item["category_code"],
                "group": group,
                "check": item["check"],
                "key": item["key"],
                "nature": nature,
                "count": item["count"],
                "example": item["example"],
            }


# ---------------------------------------------------------------------------
# Textos (en / pt / es); chaves ausentes vêm de ``proc.problem_report.TEXTS``
# ---------------------------------------------------------------------------

TEXTS = {
    **an.TEXTS,
    "title": {
        "en": "HTML to XML conversion report",
        "pt": "Relatório da conversão HTML para XML",
        "es": "Informe de la conversión HTML a XML",
    },
    "sheet_summary": {"en": "Summary by category", "pt": "Resumo por categoria", "es": "Resumen por categoría"},
    "sheet_findings": {"en": "Findings by article", "pt": "Achados por artigo", "es": "Hallazgos por artículo"},
    "sheet_articles": {"en": "Articles", "pt": "Artigos", "es": "Artículos"},
    "sheet_journals": {"en": "By journal", "pt": "Por periódico", "es": "Por revista"},
    "sheet_status": {"en": "Status", "pt": "Status", "es": "Estado"},
    "sheet_checks": {"en": "Checks", "pt": "Verificações", "es": "Verificaciones"},
    # colunas
    "group": {"en": "Group", "pt": "Grupo", "es": "Grupo"},
    "check": {"en": "Check", "pt": "Verificação", "es": "Verificación"},
    "check_code": {"en": "Check (code)", "pt": "Verificação (código)", "es": "Verificación (código)"},
    "key": {"en": "Detail (pattern)", "pt": "Detalhe (padrão)", "es": "Detalle (patrón)"},
    "nature": {"en": "Probable nature", "pt": "Natureza provável", "es": "Naturaleza probable"},
    "articles": {"en": "Articles", "pt": "Artigos", "es": "Artículos"},
    "percent": {"en": "% of analyzed", "pt": "% dos analisados", "es": "% de los analizados"},
    "occurrences": {"en": "Occurrences", "pt": "Ocorrências", "es": "Ocurrencias"},
    "count": {"en": "Occurrences in the article", "pt": "Ocorrências no artigo", "es": "Ocurrencias en el artículo"},
    "top_journal": {"en": "Most affected journal", "pt": "Periódico mais afetado", "es": "Revista más afectada"},
    "top_journal_share": {"en": "% in that journal", "pt": "% nesse periódico", "es": "% en esa revista"},
    "spread": {"en": "Spread", "pt": "Abrangência", "es": "Alcance"},
    "example": {"en": "Example", "pt": "Exemplo", "es": "Ejemplo"},
    "html2xml_status": {"en": "Conversion status", "pt": "Status da conversão", "es": "Estado de la conversión"},
    "xml_status": {"en": "XML status (article)", "pt": "Status do XML (artigo)", "es": "Estado del XML (artículo)"},
    "quality": {"en": "Quality", "pt": "Qualidade", "es": "Calidad"},
    "converted_at": {"en": "Converted at", "pt": "Convertido em", "es": "Convertido el"},
    "article_type": {"en": "article-type", "pt": "article-type", "es": "article-type"},
    "n_paragraphs": {"en": "Paragraphs (base)", "pt": "Parágrafos (base)", "es": "Párrafos (base)"},
    "n_references": {"en": "References (base)", "pt": "Referências (base)", "es": "Referencias (base)"},
    "mixed_citation": {"en": "mixed-citation", "pt": "mixed-citation", "es": "mixed-citation"},
    "element_citation": {"en": "element-citation", "pt": "element-citation", "es": "element-citation"},
    "html_tables": {"en": "HTML tables", "pt": "Tabelas no HTML", "es": "Tablas en el HTML"},
    "table_wraps": {"en": "table-wrap", "pt": "table-wrap", "es": "table-wrap"},
    "html_images": {"en": "HTML images", "pt": "Imagens no HTML", "es": "Imágenes en el HTML"},
    "xml_graphics": {"en": "graphic + inline-graphic", "pt": "graphic + inline-graphic", "es": "graphic + inline-graphic"},
    "html_langs": {"en": "Languages (HTML)", "pt": "Idiomas (HTML)", "es": "Idiomas (HTML)"},
    "xml_langs": {"en": "Languages (XML)", "pt": "Idiomas (XML)", "es": "Idiomas (XML)"},
    "categories": {"en": "Categories", "pt": "Categorias", "es": "Categorías"},
    "total_findings": {"en": "Categories in the article", "pt": "Categorias no artigo", "es": "Categorías en el artículo"},
    "analyzed": {"en": "Analyzed articles", "pt": "Artigos analisados", "es": "Artículos analizados"},
    "with_findings": {"en": "Articles with findings", "pt": "Artigos com achados", "es": "Artículos con hallazgos"},
    "top_categories": {"en": "Main categories", "pt": "Principais categorias", "es": "Categorías principales"},
    "link": {"en": "Link (conversion: steps ZIP and report)", "pt": "Link (conversão: ZIP dos passos e relatório)", "es": "Enlace (conversión: ZIP de los pasos e informe)"},
    "description": {"en": "Description", "pt": "Descrição", "es": "Descripción"},
    # abrangência
    "spread_single": {"en": "1 journal (likely data)", "pt": "1 periódico (provável dado)", "es": "1 revista (probable dato)"},
    "spread_concentrated": {
        "en": "concentrated in 1 journal",
        "pt": "concentrado em 1 periódico",
        "es": "concentrado en 1 revista",
    },
    "spread_spread": {
        "en": "spread (likely systematic)",
        "pt": "difuso (provável sistemático)",
        "es": "difuso (probable sistemático)",
    },
    # leia-me
    "total_analyzed": {"en": "Analyzed articles", "pt": "Artigos analisados", "es": "Artículos analizados"},
    "total_with_findings": {"en": "Articles with findings", "pt": "Artigos com achados", "es": "Artículos con hallazgos"},
    "desc_sheet_summary": {
        "en": "categories sorted by number of articles (C001 = most frequent), with spread and examples",
        "pt": "categorias ordenadas por quantidade de artigos (C001 = mais frequente), com abrangência e exemplos",
        "es": "categorías ordenadas por cantidad de artículos (C001 = la más frecuente), con alcance y ejemplos",
    },
    "desc_sheet_findings": {
        "en": "one row per article and category, with an example (HTML/XML snippet or message)",
        "pt": "uma linha por artigo e categoria, com um exemplo (trecho HTML/XML ou mensagem)",
        "es": "una fila por artículo y categoría, con un ejemplo (fragmento HTML/XML o mensaje)",
    },
    "desc_sheet_articles": {
        "en": "one row per analyzed article, with the counters and the categories found",
        "pt": "uma linha por artigo analisado, com os contadores e as categorias encontradas",
        "es": "una fila por artículo analizado, con los contadores y las categorías encontradas",
    },
    "desc_sheet_journals": {
        "en": "one row per journal: proportion of articles with findings and main categories",
        "pt": "uma linha por periódico: proporção de artigos com achados e principais categorias",
        "es": "una fila por revista: proporción de artículos con hallazgos y categorías principales",
    },
    "desc_sheet_status": {
        "en": "distribution of conversion status and quality in the scope",
        "pt": "distribuição de status e qualidade da conversão no escopo",
        "es": "distribución de estado y calidad de la conversión en el alcance",
    },
    "desc_sheet_checks": {
        "en": "what each check means",
        "pt": "o que significa cada verificação",
        "es": "qué significa cada verificación",
    },
    "how_to_read": {"en": "How to read", "pt": "Como ler", "es": "Cómo leer"},
    "how_to_read_1": {
        "en": "converter bug + spread (many journals) -> systematic problem: fix the converter (scielo_classic_website); one fix solves many articles",
        "pt": "bug do conversor + difuso (muitos periódicos) -> problema sistemático: corrigir o conversor (scielo_classic_website); uma correção resolve muitos artigos",
        "es": "bug del conversor + difuso (muchas revistas) -> problema sistemático: corregir el conversor (scielo_classic_website); una corrección resuelve muchos artículos",
    },
    "how_to_read_2": {
        "en": "concentrated in 1 journal -> probably particular HTML/data of that journal: check its source files",
        "pt": "concentrado em 1 periódico -> provavelmente HTML/dado particular daquele periódico: verificar os arquivos de origem",
        "es": "concentrado en 1 revista -> probablemente HTML/dato particular de esa revista: verificar sus archivos de origen",
    },
    "how_to_read_3": {
        "en": "the Link column opens the conversion of the article in the admin: generated XML, report and ZIP with the output of each step",
        "pt": "a coluna Link abre a conversão do artigo no admin: XML gerado, relatório e ZIP com a saída de cada passo",
        "es": "la columna Enlace abre la conversión del artículo en el admin: XML generado, informe y ZIP con la salida de cada paso",
    },
    "text_lost_percent": {"en": "% of text lost", "pt": "% do texto perdido", "es": "% del texto perdido"},
    "attention": {"en": "Attention points", "pt": "Pontos de atenção", "es": "Puntos de atención"},
    "how_to_read_0": {
        "en": "categories are sorted by severity (critical: content lost or conversion failed; major: defective XML; minor; information) and, in each severity, by number of articles",
        "pt": "as categorias estão ordenadas por gravidade (crítico: conteúdo perdido ou falha na conversão; importante: XML defeituoso; menor; informação) e, em cada gravidade, por quantidade de artigos",
        "es": "las categorías están ordenadas por gravedad (crítico: contenido perdido o fallo en la conversión; importante: XML defectuoso; menor; información) y, en cada gravedad, por cantidad de artículos",
    },
    "conversions_between": {
        "en": "Articles converted between",
        "pt": "Artigos convertidos entre",
        "es": "Artículos convertidos entre",
    },
}


def t(key, lang):
    entry = TEXTS.get(key) or pr.TEXTS[key]
    return entry.get(lang) or entry["en"]


# (chave do título, chave do dado)
SUMMARY_COLUMNS = [
    ("category", "code"),
    ("severity", "severity_label"),
    ("articles", "total"),
    ("percent", "percent"),
    ("journals", "total_journals"),
    ("issues", "total_issues"),
    ("collections", "total_collections"),
    ("group", "group_label"),
    ("check", "check_label"),
    ("key", "key"),
    ("nature", "nature_label"),
    ("spread", "spread_label"),
    ("top_journal", "top_journal"),
    ("top_journal_share", "top_journal_share"),
    ("occurrences", "occurrences"),
    ("example", "example"),
    ("examples", "examples"),
    ("check_code", "check"),
]

FINDINGS_COLUMNS = [
    ("item", "item"),
    ("collection", "collection"),
    ("journal", "journal_acron"),
    ("issue", "issue_folder"),
    ("pid", "pid"),
    ("package", "pkg_name"),
    ("html2xml_status", "html2xml_status"),
    ("quality", "quality"),
    ("category", "category_code"),
    ("severity", "severity_label"),
    ("group", "group_label"),
    ("check", "check_label"),
    ("key", "key"),
    ("nature", "nature_label"),
    ("count", "count"),
    ("example", "example"),
    ("link", "admin_url"),
]

ARTICLES_COLUMNS = [
    ("item", "item"),
    ("collection", "collection"),
    ("journal", "journal_acron"),
    ("issue", "issue_folder"),
    ("pid", "pid"),
    ("package", "pkg_name"),
    ("xml_status", "xml_status"),
    ("html2xml_status", "html2xml_status"),
    ("quality", "quality"),
    ("converted_at", "converted_at"),
    ("article_type", "article_type"),
    ("severity", "severity_label"),
    ("attention", "attention"),
    ("text_lost_percent", "text_lost_percent"),
    ("total_findings", "total_categories"),
    ("categories", "category_codes"),
    ("n_paragraphs", "n_paragraphs"),
    ("n_references", "n_references"),
    ("mixed_citation", "mixed_citation"),
    ("element_citation", "element_citation"),
    ("html_tables", "html_tables"),
    ("table_wraps", "table_wraps"),
    ("html_images", "html_images"),
    ("xml_graphics", "xml_graphics"),
    ("html_langs", "html_langs"),
    ("xml_langs", "xml_langs"),
    ("link", "admin_url"),
]

JOURNALS_COLUMNS = [
    ("collection", "collection"),
    ("journal", "journal_acron"),
    ("analyzed", "analyzed"),
    ("with_findings", "with_findings"),
    ("percent", "percent"),
    ("top_categories", "top_categories"),
]

STATUS_COLUMNS = [
    ("html2xml_status", "html2xml_status"),
    ("quality", "quality"),
    ("total", "total"),
]

CHECKS_COLUMNS = [
    ("check_code", "check"),
    ("check", "check_label"),
    ("severity", "severity_label"),
    ("group", "group_label"),
    ("nature", "nature_label"),
    ("description", "description"),
]

FILE_KINDS = ("summary", "findings", "articles", "journals", "status", "checks", "readme")


def _label(rows, lang):
    for row in rows:
        row = dict(row)
        if row.get("check"):
            row["check_label"] = t(f"check_{row['check']}", lang)
        if row.get("group"):
            row["group_label"] = t(f"group_{row['group']}", lang)
        if row.get("nature"):
            row["nature_label"] = t(f"nature_{row['nature']}", lang)
        if row.get("spread"):
            row["spread_label"] = t(f"spread_{row['spread']}", lang)
        if row.get("severity"):
            row["severity_label"] = t(f"severity_{row['severity']}", lang)
        yield row


def _check_rows():
    for check, (group, nature) in CHECKS.items():
        yield {"check": check, "group": group, "nature": nature, "severity": an.severity(check)}


def _check_rows_labeled(lang):
    for row in _label(_check_rows(), lang):
        row["description"] = t(f"desc_{row['check']}", lang)
        yield row


def _readme_rows(data, lang):
    rows, summary, scope = data["rows"], data["summary"], data["scope"]
    lines = [[t("title", lang)]]
    partial = data.get("partial")
    if partial:
        lines += [
            [],
            [t("incomplete", lang), t(f"partial_{partial['reason']}", lang)],
            ["", t("partial_hint", lang)],
        ]
        if partial.get("detail"):
            lines.append(["", partial["detail"]])
    natures = Counter()
    for group in summary:
        natures[group["nature"]] += group["total"]
    lines += [
        [],
        [t("generated_at", lang), pr._iso(data["generated_at"])],
        [t("scope", lang), json.dumps(scope, ensure_ascii=False, default=str)],
        [
            t("conversions_between", lang),
            f"{scope.get('updated_from') or '…'} — {scope.get('updated_to') or '…'}",
        ],
        [t("total_analyzed", lang), len(rows)],
        [t("total_with_findings", lang), sum(1 for r in rows if r["findings"])],
        [t("total_categories", lang), len(summary)],
    ]
    for item_type, cov in (data.get("coverage") or {}).items():
        lines.append([
            f"{t('coverage', lang)}: {t(f'type_{item_type}', lang)}",
            f"{cov['processed']} {t('of', lang)} {cov['total']}",
        ])
    lines += [[], [t("how_to_read", lang)]]
    for i in (0, 1, 2, 3):
        lines.append(["", t(f"how_to_read_{i}", lang)])
    lines += [[], [t("sheets", lang)]]
    for kind in FILE_KINDS[:-1]:
        lines.append([t(f"sheet_{kind}", lang), t(f"desc_sheet_{kind}", lang)])
    return lines


def _tables(data, lang):
    return [
        ("summary", SUMMARY_COLUMNS, _label(data["summary"], lang)),
        ("findings", FINDINGS_COLUMNS, _label(finding_rows(data["rows"]), lang)),
        ("articles", ARTICLES_COLUMNS, _label(data["rows"], lang)),
        ("journals", JOURNALS_COLUMNS, data["journals"]),
        ("status", STATUS_COLUMNS, data["overview"]),
        ("checks", CHECKS_COLUMNS, _check_rows_labeled(lang)),
        ("readme", None, _readme_rows(data, lang)),
    ]


def write_zip(data, lang, fileobj):
    """ZIP com um CSV por tabela (mesmo formato do relatório de problemas)."""
    names = []
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as zf:
        for number, (kind, columns, rows) in enumerate(_tables(data, lang), start=1):
            filename = f"{number}-{pr._ascii_slug(t('sheet_' + kind, lang))}.csv"
            with zf.open(filename, "w", force_zip64=True) as stream:
                if columns is None:
                    pr._write_csv(stream, None, ([pr.safe_text(v) for v in line] for line in rows))
                else:
                    pr._write_csv(
                        stream,
                        [t(c[0], lang) for c in columns],
                        ([pr.safe_text(row.get(key, "")) for _, key in columns] for row in rows),
                    )
            names.append(filename)
    return names


def build_report(
    scope,
    item_types=None,
    language="en",
    generated_at=None,
    time_budget=None,
    max_items=None,
    memory_limit=None,
):
    """
    Mesma interface de ``proc.problem_report.build_report`` (``item_types``
    é ignorado: só artigos). Retorna (arquivo temporário com o ZIP, stats).
    """
    language = language if language in pr.LANGUAGES else "en"
    generated_at = generated_at or timezone.now()
    deadline = time.monotonic() + time_budget if time_budget is not None else None
    collected = collect(scope, deadline=deadline, max_items=max_items, memory_limit=memory_limit)
    rows = collected["rows"]
    summary = summarize(rows, collected["categories"])
    data = {
        "scope": scope,
        "generated_at": generated_at,
        "rows": rows,
        "summary": summary,
        "journals": by_journal(rows),
        "overview": collected["overview"],
        "coverage": collected["coverage"],
        "partial": collected["partial"],
    }
    fileobj = tempfile.TemporaryFile()
    try:
        filenames = write_zip(data, language, fileobj)
        fileobj.seek(0)
    except Exception:
        fileobj.close()
        raise

    with_findings = sum(1 for r in rows if r["findings"])
    stats = {
        "language": language,
        "files": filenames,
        "partial": collected["partial"],
        "coverage": collected["coverage"],
        "total_analyzed": len(rows),
        "total_items": with_findings,
        "total_categories": len(summary),
        "by_group": dict(Counter(g["group"] for g in summary)),
        "by_nature": dict(Counter(g["nature"] for g in summary)),
        "by_severity": dict(Counter(r["severity"] or "none" for r in rows)),
        "top_categories": [
            {k: g[k] for k in (
                "code", "severity", "total", "percent", "total_journals", "group", "check",
                "key", "nature", "spread", "top_journal", "examples",
            )}
            for g in summary[:30]
        ],
    }
    return fileobj, stats
