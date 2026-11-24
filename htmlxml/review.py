"""
Revisão da conversão HTML -> XML.

Substitui os "pontos de atenção" e o relatório por artigo (que exigiam
abrir artigo por artigo) por **categorias de problema** persistidas
(``Html2xmlIssueCategory``, global), acompanhadas por coleção
(``Html2xmlProblem``) e ligadas às conversões em que ocorrem
(``Html2xmlIssue``). Quem revisa (gestor da coleção ou administrador)
trabalha por problema: classifica (bug do conversor, dado, esperado,
corrigido) e decide se bloqueia a publicação no site novo; a decisão vale
para todos os artigos da coleção com o problema.

A revisão:

- roda ao fim de cada conversão (``HTMLXML.html_to_xml``) e nunca a
  interrompe;
- pode ser solicitada pelo gestor da coleção (formulário no admin) ou pelo
  comando ``review_html2xml``, para conversões existentes, a partir dos
  arquivos gravados, sem reconverter;
- usa as regras de ``htmlxml.analysis`` (as mesmas do relatório CSV da
  coleção).
"""

import logging
import zipfile

from django.db import transaction
from django.utils import timezone
from lxml import etree

from htmlxml import analysis
from tracker import choices as tracker_choices

OK = "ok"


def _parse_file(field):
    if not field or not field.name:
        raise FileNotFoundError("(no file)")
    with field.storage.open(field.name, "rb") as fp:
        return etree.parse(fp, etree.XMLParser(huge_tree=True)).getroot()


def initial_html(htmlxml):
    """
    HTML inicial (estruturado em body/back): ``bb_init_file`` ou, nas
    conversões antigas que não o têm, o passo 2 do ZIP de passos.
    """
    try:
        return _parse_file(htmlxml.bb_init_file)
    except Exception:
        pass
    zip_field = htmlxml.conversion_steps_zip_file
    if zip_field and zip_field.name:
        try:
            with zip_field.storage.open(zip_field.name, "rb") as fp:
                with zipfile.ZipFile(fp) as zf:
                    return etree.fromstring(zf.read("step_002.xml"), etree.XMLParser(huge_tree=True))
        except Exception:
            pass
    return None


def counters(htmlxml):
    """Contadores usados pelas verificações de conteúdo."""
    names = [
        "empty_body", "article_type", "html_img_total", "html_table_total",
        "xml_supplmat_total", "xml_media_total", "xml_fig_total",
        "xml_table_wrap_total", "xml_eq_total", "xml_graphic_total",
        "xml_inline_graphic_total", "xml_ref_elem_citation_total",
        "xml_ref_mixed_citation_total", "xml_text_lang_total",
        "n_paragraphs", "n_references", "html_translation_langs",
    ]
    return {name: getattr(htmlxml, name, None) for name in names}


def _location(article_proc):
    if article_proc is None:
        return {"collection_acron": "", "journal_acron": "", "issue_folder": "", "pid": ""}
    try:
        journal_acron = article_proc.issue_proc.journal_proc.acron or ""
    except AttributeError:
        journal_acron = ""
    try:
        issue_folder = article_proc.issue_proc.issue_folder or ""
    except AttributeError:
        issue_folder = ""
    try:
        collection_acron = article_proc.collection.acron or ""
    except AttributeError:
        collection_acron = ""
    return {
        "collection_acron": collection_acron[:16],
        "journal_acron": journal_acron[:32],
        "issue_folder": issue_folder[:32],
        "pid": (article_proc.pid or "")[:23],
    }


def find_findings(htmlxml, detail, journal_acron=""):
    """
    Achados da conversão: falhas registradas em ``detail`` (evento
    ``html_to_xml``) e, havendo XML, a avaliação de ``htmlxml.analysis``.
    Atualiza os contadores de ``htmlxml`` (sem gravar).
    Retorna (achados, % de texto perdido ou None).
    """
    status = htmlxml.html2xml_status
    findings = analysis.failure_findings(status, detail, has_event=detail is not None)
    if status not in analysis.STATUS_WITH_XML:
        return findings, None
    try:
        xml = _parse_file(htmlxml.file)
    except Exception as e:
        findings.append(analysis.finding("xml_unreadable", type(e).__name__, example=str(e)))
        return findings, None
    html = initial_html(htmlxml)

    # contadores (mesmos métodos do relatório antigo)
    htmlxml.article_type = xml.get("article-type")
    htmlxml.get_xml_stats(xml)
    if html is not None:
        htmlxml.get_html_stats(html)
    else:
        findings.append(analysis.finding("initial_html_unreadable"))

    result = analysis.evaluate(html, xml, counters(htmlxml), journal_acron)
    findings.extend(result["findings"])
    text = result["text"]
    return findings, (text["percent"] if text and text["compared"] else None)


def _merge(findings):
    """Uma ocorrência por (verificação, chave), somando as quantidades."""
    merged = {}
    for item in findings:
        k = (item["check"], item["key"])
        if k in merged:
            merged[k]["count"] += item["count"] or 0
        else:
            merged[k] = dict(item)
    return list(merged.values())


def review_conversion(htmlxml, article_proc=None, detail=None, user=None):
    """
    Revisa uma conversão e grava o resultado: categorias e ocorrências
    (substituindo as anteriores desta conversão), gravidade máxima e % de
    texto perdido. Retorna ``{"severity", "text_lost", "issues",
    "blocking"}``.
    """
    from htmlxml.models import Html2xmlIssue, Html2xmlIssueCategory, Html2xmlProblem

    location = _location(article_proc)
    collection = getattr(article_proc, "collection", None) if article_proc else None
    findings, text_lost = find_findings(htmlxml, detail, location["journal_acron"])
    findings = _merge(findings)
    now = timezone.now()

    with transaction.atomic():
        Html2xmlIssue.objects.filter(htmlxml=htmlxml).delete()
        issues = []
        for item in findings:
            category = Html2xmlIssueCategory.get_or_create_for(item["check"], item["key"], item["example"])
            problem = Html2xmlProblem.get_or_create_for(collection, category)
            issues.append(Html2xmlIssue(
                htmlxml=htmlxml,
                problem=problem,
                count=item["count"] or 1,
                example=item["example"] or "",
                **location,
            ))
        Html2xmlIssue.objects.bulk_create(issues)
        if issues:
            Html2xmlProblem.objects.filter(
                pk__in={i.problem_id for i in issues}
            ).update(last_seen=now)

        htmlxml.review_severity = analysis.max_severity(findings) or OK
        htmlxml.review_text_lost = text_lost
        htmlxml.reviewed_at = now
        fields = ["review_severity", "review_text_lost", "reviewed_at", "article_type"] + [
            f for f in counters(htmlxml) if f.startswith(("html_img", "html_table", "xml_", "empty_"))
        ]
        htmlxml.save(update_fields=fields)

    blocking = [i.problem.category for i in issues if i.problem.blocks_publication]
    return {
        "severity": htmlxml.review_severity,
        "text_lost": text_lost,
        "issues": len(issues),
        "blocking": [str(c) for c in blocking],
    }


def last_conversion_detail(article_proc):
    """``detail`` do último evento ``html_to_xml`` do artigo (ou None)."""
    if article_proc is None:
        return None
    event = (
        article_proc.article_proc_result.filter(name="html_to_xml")
        .order_by("-created")
        .values("detail")
        .first()
    )
    return event["detail"] if event else None


def review_existing(htmlxml, user=None):
    """Revisa uma conversão já feita (sem reconverter)."""
    from proc.models import ArticleProc

    article_proc = (
        ArticleProc.objects.filter(migrated_data=htmlxml.migrated_article)
        .select_related("issue_proc__journal_proc", "collection")
        .first()
    )
    return review_conversion(
        htmlxml,
        article_proc=article_proc,
        detail=last_conversion_detail(article_proc),
        user=user,
    )


def queryset_to_review(collection_acron_list=None, journal_acron_list=None, updated_from=None,
                       updated_to=None, only_not_reviewed=False):
    from htmlxml.models import HTMLXML
    from proc import problem_report as pr

    qs = HTMLXML.objects.exclude(html2xml_status=tracker_choices.PROGRESS_STATUS_TODO)
    if collection_acron_list:
        qs = qs.filter(migrated_article__collection__acron__in=collection_acron_list)
    if journal_acron_list:
        qs = qs.filter(
            migrated_article__articleproc__issue_proc__journal_proc__acron__in=journal_acron_list
        ).distinct()
    start, end = pr.updated_range({"updated_from": updated_from, "updated_to": updated_to})
    if start:
        qs = qs.filter(updated__gte=start)
    if end:
        qs = qs.filter(updated__lt=end)
    if only_not_reviewed:
        qs = qs.filter(reviewed_at__isnull=True)
    return qs.order_by("-updated")


def review_many(qs, user=None, limit=None):
    """Revisa as conversões de ``qs``; retorna contagens por gravidade."""
    from collections import Counter

    result = Counter()
    for i, htmlxml in enumerate(qs.iterator(chunk_size=200)):
        if limit and i >= limit:
            break
        try:
            result[review_existing(htmlxml, user)["severity"]] += 1
        except Exception as e:
            logging.exception(f"review {htmlxml}: {e}")
            result["(error)"] += 1
    return dict(result)
