"""
Avaliação da conversão HTML -> XML de um artigo.

Compara o HTML inicial (estruturado em body/back) com o XML gerado e
produz uma lista de "achados", cada um com uma verificação (``check``), uma
chave (padrão que agrupa ocorrências iguais em artigos diferentes), a
quantidade e um exemplo. Cada verificação tem um grupo, uma natureza
provável (bug do conversor, mapeamento ausente, dado de origem, a
verificar) e uma gravidade:

- ``critical``: perda de conteúdo (texto, body, referências, traduções,
  figuras/tabelas vazias) ou falha da conversão;
- ``major``: XML defeituoso (elementos fora do JATS, ``xref`` quebrado,
  ``id`` duplicado...);
- ``minor``: valores sem mapeamento, links/âncoras do HTML sem
  correspondente;
- ``info``: diferenças esperadas ou não verificáveis.

Os pontos de atenção de um artigo são os achados críticos e importantes;
sem eles, a conversão é aprovada automaticamente.

Usada pelo relatório de cada conversão (``HTMLXML``) e pelo relatório da
coleção (``proc.html2xml_report``), para que ambos sigam as mesmas regras.
"""

import os
import re
from bisect import bisect_right
from collections import Counter

from lxml import etree

from proc import problem_report as pr
from tracker import choices as tracker_choices

XLINK = "http://www.w3.org/1999/xlink"
NAMESPACES = {"xlink": XLINK}

MAX_EXAMPLE = 400
MAX_KEY = 200

# ---------------------------------------------------------------------------
# Verificações
# ---------------------------------------------------------------------------

GROUP_FAILURE = "failure"
GROUP_CONTENT = "content"
GROUP_STRUCTURE = "structure"
GROUP_HTML = "html"
GROUPS = (GROUP_FAILURE, GROUP_CONTENT, GROUP_STRUCTURE, GROUP_HTML)

# natureza provável (independe da abrangência, que é calculada)
NATURE_BUG = "bug"
NATURE_DATA = "data"
NATURE_MAPPING = "mapping"
NATURE_CHECK = "check"
NATURES = (NATURE_BUG, NATURE_MAPPING, NATURE_DATA, NATURE_CHECK)

# check -> (grupo, natureza)
CHECKS = {
    "step_failure": (GROUP_FAILURE, NATURE_BUG),
    "step_failure_after": (GROUP_FAILURE, NATURE_BUG),
    "conversion_exception": (GROUP_FAILURE, NATURE_BUG),
    "conversion_blocked": (GROUP_FAILURE, NATURE_BUG),
    "report_error": (GROUP_FAILURE, NATURE_BUG),
    "zip_error": (GROUP_FAILURE, NATURE_BUG),
    "no_event": (GROUP_FAILURE, NATURE_CHECK),
    "xml_unreadable": (GROUP_FAILURE, NATURE_BUG),
    "body_lost": (GROUP_CONTENT, NATURE_BUG),
    "no_html_text": (GROUP_CONTENT, NATURE_DATA),
    "refs_missing": (GROUP_CONTENT, NATURE_BUG),
    "refs_count_differs": (GROUP_CONTENT, NATURE_CHECK),
    "refs_elem_vs_mixed": (GROUP_CONTENT, NATURE_BUG),
    "translation_missing": (GROUP_CONTENT, NATURE_BUG),
    "article_type_not_jats": (GROUP_CONTENT, NATURE_MAPPING),
    "images_fewer_in_xml": (GROUP_CONTENT, NATURE_CHECK),
    "tables_fewer_in_xml": (GROUP_CONTENT, NATURE_CHECK),
    "non_jats_element": (GROUP_STRUCTURE, NATURE_BUG),
    "xref_broken_rid": (GROUP_STRUCTURE, NATURE_BUG),
    "xref_ref_type_invalid": (GROUP_STRUCTURE, NATURE_MAPPING),
    "duplicate_id": (GROUP_STRUCTURE, NATURE_BUG),
    "table_wrap_empty": (GROUP_STRUCTURE, NATURE_BUG),
    "fig_empty": (GROUP_STRUCTURE, NATURE_BUG),
    "html_not_converted": (GROUP_HTML, NATURE_CHECK),
    "initial_html_unreadable": (GROUP_HTML, NATURE_CHECK),
    "text_lost": (GROUP_CONTENT, NATURE_BUG),
    "short_text_lost": (GROUP_CONTENT, NATURE_CHECK),
    "text_not_compared": (GROUP_CONTENT, NATURE_CHECK),
    "front_in_body": (GROUP_CONTENT, NATURE_BUG),
}

# status em que há XML gerado (contadores e arquivo válidos)
STATUS_WITH_XML = (
    tracker_choices.PROGRESS_STATUS_DONE,
    tracker_choices.PROGRESS_STATUS_PENDING,
)
STATUS_PROBLEM = (
    tracker_choices.PROGRESS_STATUS_BLOCKED,
    tracker_choices.PROGRESS_STATUS_PENDING,
)

# JATS 1.3 (Publishing); elementos com namespace (mml, etc.) não são avaliados
JATS_ELEMENTS = frozenset(
    """
    abbrev abbrev-journal-title abstract access-date ack addr-line address aff
    aff-alternatives alt-text alt-title alternatives annotation anonymous answer
    answer-set app app-group array article article-categories article-id
    article-meta article-title article-version article-version-alternatives
    attrib author-comment author-notes award-desc award-group award-id award-name
    back bio block-alternatives body bold boxed-text break caption chapter-title
    chem-struct chem-struct-wrap citation-alternatives city code col colgroup
    collab collab-alternatives comment compound-kwd compound-kwd-part
    compound-subject compound-subject-part conf-acronym conf-date conf-loc
    conf-name conf-num conf-sponsor conf-theme conference contrib contrib-group
    contrib-id copyright-holder copyright-statement copyright-year corresp count
    country counts custom-meta custom-meta-group data-title date
    date-in-citation day def def-head def-item def-list degrees disp-formula
    disp-formula-group disp-quote edition element-citation elocation-id email
    equation-count era etal event event-desc explanation ext-link extended-by
    fax fig fig-count fig-group fixed-case floats-group fn fn-group fpage front
    front-stub funding-group funding-source funding-statement given-names
    glossary glyph-data glyph-ref gov graphic history hr inline-formula
    inline-graphic inline-media inline-supplementary-material institution
    institution-id institution-wrap isbn issn issn-l issue issue-id issue-part
    issue-sponsor issue-subtitle issue-title issue-title-group italic journal-id
    journal-meta journal-subtitle journal-title journal-title-group kwd
    kwd-group label license license-p list list-item long-desc lpage media
    meta-name meta-value milestone-end milestone-start mixed-citation monospace
    month name name-alternatives named-content nested-kwd nlm-citation note
    notes object-id on-behalf-of open-access overline overline-end
    overline-start p page-count page-range part-title patent permissions
    person-group phone postal-code prefix preformat price
    principal-award-recipient principal-investigator private-char
    processing-meta product pub-date pub-date-not-available pub-history pub-id
    publisher publisher-loc publisher-name question question-preamble
    question-wrap question-wrap-group rb ref ref-count ref-list related-article
    related-object resource-group resource-id resource-name resource-wrap
    response role roman rp rt ruby sans-serif sc season sec sec-meta see
    see-also self-uri series series-text series-title sig sig-block size source
    speaker speech state statement std std-organization strike string-conf
    string-date string-name styled-content sub sub-article subj-group subject
    subtitle suffix sup supplement supplementary-material support-description
    support-group support-source surname table table-count table-wrap
    table-wrap-foot table-wrap-group target tbody td term term-head tex-math
    textual-form tfoot th thead time-stamp title title-group tr trans-abstract
    trans-source trans-subtitle trans-title trans-title-group underline
    underline-end underline-start unstructured-kwd-group uri verse-group
    verse-line version volume volume-id volume-issue-group volume-series
    word-count x xref year
    """.split()
)

JATS_REF_TYPES = frozenset(
    """
    aff app author-notes award bibr bio boxed-text chem collab contrib corresp
    custom disp-formula fig fn kwd list other plate scheme sec statement
    supplementary-material table table-fn
    """.split()
)

JATS_ARTICLE_TYPES = frozenset(
    """
    abstract addendum announcement article-commentary book-review
    books-received brief-report calendar case-report clinical-trial collection
    correction data-article discussion dissertation editorial
    editorial-material expression-of-concern guideline in-brief interview
    introduction letter meeting-report methods-article news obituary oration
    other partial-retraction product-review rapid-communication reply reprint
    research-article retraction review-article reviewer-report
    systematic-review translation
    """.split()
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".tif", ".tiff"}

_STEP_RE = re.compile(r"step\s+(\d+)\s+failed\s+(\S+)")
_FRAME_RE = re.compile(r'File "([^"]+)", line \d+, in (\S+)')
_XMLNS_RE = re.compile(r'\s+xmlns(?::[\w.-]+)?="[^"]*"')


def finding(check, key="", count=1, example=""):
    return {
        "check": check,
        "key": (key or "")[:MAX_KEY],
        "count": count,
        "example": (example or "")[:MAX_EXAMPLE],
    }


def _text(value):
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def code_location(traceback_text):
    """
    Ponto do código onde a exceção ocorreu, como ``arquivo.py:função``: o
    frame mais interno da biblioteca de conversão
    (``scielo_classic_website``); sem ele, o mais interno do traceback.
    """
    frames = _FRAME_RE.findall(_text(traceback_text))
    if not frames:
        return ""
    chosen = None
    for path, func in frames:
        if "scielo_classic_website" in path:
            chosen = (path, func)
    path, func = chosen or frames[-1]
    return f"{os.path.basename(path)}:{func}"


def exception_signature(exc_type, traceback_text):
    """(tipo, local no código, mensagem normalizada, mensagem concreta)."""
    tb_type, message = pr.last_traceback_line(_text(traceback_text))
    if not message and not tb_type:
        message = _text(traceback_text).strip().splitlines()[-1] if _text(traceback_text).strip() else ""
    exc = pr.clean_exception_type(exc_type) if exc_type else ""
    if not exc or exc in ("str", "builtins.str"):
        exc = tb_type
    return exc, code_location(traceback_text), pr.normalize_text(message, 160), message


def _signature_key(*parts):
    return " | ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# 1. Falhas (evento html_to_xml)
# ---------------------------------------------------------------------------


def failure_findings(html2xml_status, detail, has_event=True):
    """
    Achados do ``detail`` do último evento ``html_to_xml`` do artigo.

    Os passos da conversão são encadeados: quando um passo falha, os
    seguintes costumam falhar por consequência. O 1º passo com falha é
    ``step_failure`` (causa); os seguintes, ``step_failure_after``.
    """
    found = []
    if not has_event:
        if html2xml_status in STATUS_PROBLEM:
            found.append(finding("no_event", html2xml_status))
        return found
    if not isinstance(detail, dict):
        if detail:
            exc, where, template, message = exception_signature("", _text(detail))
            found.append(finding("conversion_exception", _signature_key(exc, where, template), example=message))
        return found

    steps = []
    others = []
    for item in detail.get("exceptions") or []:
        if not isinstance(item, dict):
            exc, where, template, message = exception_signature("", _text(item))
            others.append(("", exc, where, template, message))
            continue
        action = _text(item.get("action"))
        exc, where, template, message = exception_signature(
            item.get("type"), item.get("message")
        )
        m = _STEP_RE.search(action)
        if m:
            steps.append((int(m.group(1)), m.group(2), exc, where, template, message))
        else:
            others.append((pr.normalize_operation(action), exc, where, template, message))

    seen = set()
    steps.sort()
    if steps:
        # causa: 1º passo com falha
        _, root_func, root_exc, root_where, root_template, root_message = steps[0]
        found.append(finding(
            "step_failure",
            _signature_key(root_func, root_exc, root_where, root_template),
            example=root_message,
        ))
        # passos seguintes com o mesmo erro: uma só ocorrência (cascata)
        same = [s for s in steps[1:] if (s[2], s[4]) == (root_exc, root_template)]
        if same:
            found.append(finding(
                "step_failure_after",
                _signature_key(f"same error as {root_func}", root_exc, root_template),
                count=len(same),
                example=", ".join(s[1] for s in same),
            ))
        # passos seguintes com outro erro: cada um é uma categoria
        for number, func, exc, where, template, message in steps[1:]:
            if (exc, template) == (root_exc, root_template):
                continue
            key = _signature_key(func, exc, where, template)
            if key in seen:
                continue
            seen.add(key)
            found.append(finding("step_failure_after", key, example=message))

    for action, exc, where, template, message in others:
        key = _signature_key(action, exc, where, template)
        if key in seen:
            continue
        seen.add(key)
        found.append(finding("conversion_exception", key, example=message))

    if detail.get("exception_message"):
        exc, where, template, message = exception_signature(
            detail.get("exception_type"), detail.get("exception_message")
        )
        found.append(finding("conversion_blocked", _signature_key(exc, where, template), example=message))

    if detail.get("report_exceptions"):
        exc, where, template, message = exception_signature("", detail["report_exceptions"])
        found.append(finding("report_error", _signature_key(exc, where, template), example=message))

    zip_errors = detail.get("zip_exceptions") or []
    if zip_errors:
        first = _text(zip_errors[0])
        found.append(finding("zip_error", pr.normalize_text(first, 160), count=len(zip_errors), example=first))
    return found


# ---------------------------------------------------------------------------
# 2. Conteúdo (contadores de HTMLXML)
# ---------------------------------------------------------------------------


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def content_findings(data):
    """
    ``data``: contadores de ``HTMLXML`` (nomes dos campos do modelo). Só
    faz sentido quando há XML gerado e avaliado.
    """
    found = []
    n_paragraphs = _int(data.get("n_paragraphs"))
    n_references = _int(data.get("n_references"))
    mixed = _int(data.get("xml_ref_mixed_citation_total"))
    elem = _int(data.get("xml_ref_elem_citation_total"))

    if data.get("empty_body"):
        if n_paragraphs:
            found.append(finding("body_lost", count=n_paragraphs, example=f"n_paragraphs={n_paragraphs}"))
        else:
            found.append(finding("no_html_text"))

    if n_references and not mixed:
        found.append(finding("refs_missing", count=n_references, example=f"n_references={n_references}, mixed-citation=0"))
    elif n_references and mixed and n_references != mixed:
        key = "fewer in XML" if mixed < n_references else "more in XML"
        found.append(finding(
            "refs_count_differs", key, count=abs(n_references - mixed),
            example=f"n_references={n_references}, mixed-citation={mixed}",
        ))
    if elem != mixed:
        found.append(finding(
            "refs_elem_vs_mixed", "fewer element-citation" if elem < mixed else "more element-citation",
            count=abs(elem - mixed), example=f"element-citation={elem}, mixed-citation={mixed}",
        ))

    langs = [x for x in _text(data.get("html_translation_langs")).split("-") if x]
    expected = len(langs) + 1
    xml_langs = _int(data.get("xml_text_lang_total"))
    if xml_langs and xml_langs < expected:
        found.append(finding(
            "translation_missing", count=expected - xml_langs,
            example=f"HTML: {expected} ({'-'.join(langs)} + main), XML: {xml_langs}",
        ))

    article_type = _text(data.get("article_type")).strip()
    if article_type not in JATS_ARTICLE_TYPES:
        found.append(finding("article_type_not_jats", article_type or "(none)", example=article_type))

    html_img = _int(data.get("html_img_total"))
    xml_img = _int(data.get("xml_graphic_total")) + _int(data.get("xml_inline_graphic_total"))
    if html_img > xml_img:
        found.append(finding(
            "images_fewer_in_xml", count=html_img - xml_img,
            example=f"img={html_img}, graphic+inline-graphic={xml_img}",
        ))
    html_tables = _int(data.get("html_table_total"))
    xml_tables = _int(data.get("xml_table_wrap_total"))
    if html_tables > xml_tables:
        found.append(finding(
            "tables_fewer_in_xml", count=html_tables - xml_tables,
            example=f"table={html_tables}, table-wrap={xml_tables}",
        ))
    return found


# ---------------------------------------------------------------------------
# 3. Estrutura do XML gerado
# ---------------------------------------------------------------------------


def _snippet(node):
    try:
        text = etree.tostring(node, encoding="unicode", with_tail=False)
    except Exception:
        return ""
    text = _XMLNS_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text[:MAX_EXAMPLE]


def _localname(node):
    """Nome sem namespace; None se não for elemento ou se tiver namespace."""
    if not isinstance(node.tag, str):
        return None
    qname = etree.QName(node)
    if qname.namespace:
        return None
    return qname.localname


class _Tally:
    """Conta ocorrências por (check, chave) guardando o 1º exemplo."""

    def __init__(self):
        self.counts = Counter()
        self.examples = {}

    def add(self, check, key, example_node=None, example_text=None):
        k = (check, key)
        self.counts[k] += 1
        if k not in self.examples:
            self.examples[k] = example_text if example_text is not None else (
                _snippet(example_node) if example_node is not None else ""
            )

    def findings(self):
        return [
            finding(check, key, count=n, example=self.examples.get((check, key), ""))
            for (check, key), n in self.counts.items()
        ]


def structure_findings(xml):
    """Defeitos estruturais no XML gerado (árvore lxml)."""
    tally = _Tally()
    ids = Counter()
    id_nodes = {}
    for node in xml.iter():
        name = _localname(node)
        if name is None:
            continue
        if name not in JATS_ELEMENTS:
            tally.add("non_jats_element", name, node)
        node_id = node.get("id")
        if node_id:
            ids[node_id] += 1
            id_nodes.setdefault(node_id, node)

    for node_id, n in ids.items():
        if n > 1:
            tally.add("duplicate_id", _localname(id_nodes[node_id]) or "?", id_nodes[node_id])

    for xref in xml.iter("xref"):
        ref_type = xref.get("ref-type")
        if ref_type not in JATS_REF_TYPES:
            tally.add("xref_ref_type_invalid", ref_type or "(none)", xref)
        for rid in (xref.get("rid") or "").split():
            if rid not in ids:
                tally.add("xref_broken_rid", ref_type or "(none)", xref)

    for node in xml.iter("table-wrap"):
        if not node.xpath(".//table|.//graphic|.//alternatives|.//inline-graphic|.//media"):
            tally.add("table_wrap_empty", "", node)
    for node in xml.iter("fig"):
        if not node.xpath(".//graphic|.//alternatives|.//media|.//inline-graphic"):
            tally.add("fig_empty", "", node)
    return tally.findings()


# ---------------------------------------------------------------------------
# 4. HTML sem correspondente no XML
# ---------------------------------------------------------------------------


def a_href_pattern(href, text, journal_acron):
    """Padrão do link (mesma ordem de ``htmlxml.models.get_xpath_for_a_href_stats``)."""
    href = (href or "").strip()
    if href.startswith("#"):
        return "a[href=#…]"
    if "@" in href or "@" in (text or ""):
        return "a[href=mailto]"
    _, ext = os.path.splitext(href.lower())
    if ext in IMAGE_EXTENSIONS or "img/revistas" in href or f"/{journal_acron}/" in href:
        return "a[href=image]"
    lower = href.lower()
    if lower.startswith("javascript:"):
        return "a[href=javascript]"
    if re.match(r"^[a-z][a-z0-9+.\-]*://", lower):
        return "a[href=url]"
    if lower.endswith((".pdf", ".htm", ".html")):
        return f"a[href=*{os.path.splitext(lower)[1]}]"
    return "a[href=other]"


def src_pattern(tag, src, journal_acron):
    if ":" in src:
        kind = "url"
    elif f"/{journal_acron}/" in src:
        kind = "journal-dir"
    else:
        kind = "other"
    return f"{tag}[src={kind}]"


def a_name_pattern(name):
    name = (name or "").strip().lower()
    if not name:
        return "a[name=]"
    if name.isalpha():
        return "a[name=word]"
    return "a[name=" + re.sub(r"\d+", "N", name)[:20] + "]"


def _matches(xml, xpaths):
    """True se algum xpath encontra nó; None se não dá para verificar."""
    if not xpaths:
        return None
    try:
        return bool(xml.xpath("|".join(xpaths), namespaces=NAMESPACES))
    except Exception:
        return None


def html_findings(html, xml, journal_acron):
    """
    Links, âncoras e imagens do HTML inicial sem correspondente no XML,
    usando as mesmas regras do relatório individual de ``HTMLXML``.
    """
    from htmlxml.models import (
        get_xpath_for_a_href_stats,
        get_xpath_for_name_stats,
        get_xpath_for_src_stats,
    )

    tally = _Tally()
    for a in html.xpath(".//a[@href]"):
        href = a.get("href") or ""
        if not href.strip():
            continue
        text = "".join(a.xpath(".//text()"))
        if _matches(xml, get_xpath_for_a_href_stats(a, journal_acron)) is False:
            tally.add("html_not_converted", a_href_pattern(href, text, journal_acron), a)
    for node in html.xpath(".//*[@src]"):
        if not isinstance(node.tag, str):
            continue
        src = node.get("src") or ""
        if _matches(xml, get_xpath_for_src_stats(node.tag, src, journal_acron)) is False:
            tally.add("html_not_converted", src_pattern(node.tag, src, journal_acron), node)
    for a in html.xpath(".//a[@name]"):
        name = a.get("name") or ""
        if _matches(xml, get_xpath_for_name_stats(name)) is False:
            tally.add("html_not_converted", a_name_pattern(name), a)
    return tally.findings()




# ---------------------------------------------------------------------------
# 5. Texto perdido
# ---------------------------------------------------------------------------
# Compara só as letras (sem espaços, pontuação e dígitos: citações
# reescritas como xref, quebras de linha etc. não contam como diferença).
# Cada bloco do HTML (parágrafo, item, célula, div sem blocos internos...) é
# verificado em pedaços de ``CHUNK`` letras; nos pedaços ausentes do XML,
# janelas de ``WINDOW`` letras localizam exatamente o trecho perdido. A
# comparação começa no 1º pedaço que aparece no body do XML: o que vem antes
# no HTML é a página de rosto (autores, afiliações, resumos), levada para o
# front.
#
# Cada trecho perdido é registrado com a marcação HTML antes → depois dele
# (ex.: ``span[sup] → a[href=#…]/span[sup]``): trechos perdidos junto à
# mesma marcação em vários periódicos indicam um bug do conversor.

BLOCK_TAGS = frozenset(
    "p li td th dd dt blockquote h1 h2 h3 h4 h5 h6 caption pre center div".split()
)
CHUNK = 60
WINDOW = 20
MIN_LOST = WINDOW  # letras
CONTEXT = 60


_LETTERS_RE = re.compile(r"[^\W\d_]+")
SHORT_BLOCK = 150  # letras: título, linha de autores, palavras-chave...


def normalize_letters(text):
    """Só as letras, em minúsculas."""
    letters = "".join(_LETTERS_RE.findall(text or ""))
    lower = letters.lower()
    if len(lower) != len(letters):
        lower = "".join(ch.lower()[:1] for ch in letters)
    return lower


def _letters_index(text):
    """Posição, no texto original, de cada letra de ``normalize_letters``."""
    index = []
    for m in _LETTERS_RE.finditer(text or ""):
        index.extend(range(m.start(), m.end()))
    return index


def _is_element(node):
    return isinstance(node.tag, str)


def _leaf_blocks(root):
    for node in root.iter():
        if not _is_element(node) or node.tag not in BLOCK_TAGS:
            continue
        if any(_is_element(d) and d.tag in BLOCK_TAGS for d in node.iterdescendants()):
            continue
        yield node


def _segments(block):
    """
    Texto do bloco e, para cada trecho, o elemento que o contém:
    (texto, [(início, fim, elemento)]).
    """
    parts = []
    segments = []
    pos = 0

    def add(text, owner):
        nonlocal pos
        if text:
            parts.append(text)
            segments.append((pos, pos + len(text), owner))
            pos += len(text)

    def visit(node):
        add(node.text, node)
        for child in node:
            if _is_element(child):
                visit(child)
            add(child.tail, node)

    visit(block)
    return "".join(parts), segments


def _owner_at(segments, starts, offset):
    if offset is None or not segments:
        return None
    i = bisect_right(starts, offset) - 1
    if i < 0:
        return None
    start, end, owner = segments[i]
    return owner if offset < end else None


_STYLE_LABELS = (("sup", "sup"), ("sub", "sub"), ("bold", "bold"), ("italic", "italic"))


def _node_desc(node):
    """Descrição da marcação que importa para agrupar (estilos visuais não)."""
    tag = node.tag
    if tag == "a":
        href = node.get("href")
        if href is not None:
            return "a[href=#…]" if href.strip().startswith("#") else "a[href]"
        if node.get("name") is not None:
            return "a[name]"
        return "a"
    if tag == "span":
        style = (node.get("style") or "").lower()
        for word, label in _STYLE_LABELS:
            if word in style:
                return f"span[{label}]"
        return None
    if tag == "font":
        face = (node.get("face") or "").lower()
        return "font[symbol]" if "symbol" in face else None
    if tag in ("small", "big", "o:p"):
        return None
    return tag


def _markup(owner, block):
    """Marcação em volta de um ponto do texto, ex.: ``a[href=#…]/span[sup]``."""
    if owner is None:
        return "(end)"
    chain = []
    node = owner
    while node is not None and node is not block:
        desc = _node_desc(node)
        if desc and (not chain or chain[-1] != desc):
            chain.append(desc)
        node = node.getparent()
    return "/".join(reversed(chain)) or "text"


def _clip(text, size, from_end=False):
    text = re.sub(r"\s+", " ", text or "")
    if from_end:
        return text[-size:].lstrip()
    return text[:size].rstrip()


class _XmlText:
    """Texto do XML (letras) com índice de janelas para busca rápida."""

    def __init__(self, xml):
        self.raw = "".join(xml.itertext())
        self.letters = normalize_letters(self.raw)
        self._windows = None
        self._index = None

    @property
    def index(self):
        if self._index is None:
            self._index = _letters_index(self.raw)
        return self._index

    @property
    def windows(self):
        # montado só quando há trecho a refinar (artigos sem perda não pagam)
        if self._windows is None:
            self._windows = {
                self.letters[k:k + WINDOW]
                for k in range(0, max(0, len(self.letters) - WINDOW + 1))
            }
        return self._windows

    def has(self, letters):
        if len(letters) == WINDOW:
            return letters in self.windows
        return letters in self.letters

    def context(self, before_letters):
        """Texto do XML no ponto que vem depois de ``before_letters``."""
        if not before_letters:
            return ""
        pos = self.letters.find(before_letters)
        if pos < 0:
            return ""
        raw_pos = self.index[pos + len(before_letters) - 1] + 1
        return (
            _clip(self.raw[max(0, raw_pos - CONTEXT):raw_pos], CONTEXT, from_end=True)
            + " [[]] "
            + _clip(self.raw[raw_pos:raw_pos + CONTEXT], CONTEXT)
        )


def _covered(norm, start, xml_text):
    """Marca as letras de ``norm[start:]`` que estão no XML."""
    n = len(norm)
    covered = bytearray(n)
    to_refine = []
    for j in range(start, n, CHUNK):
        chunk = norm[j:j + CHUNK]
        if len(chunk) < WINDOW:
            # resto curto: verifica com as letras anteriores
            k = max(start, n - WINDOW)
            if n - k >= WINDOW and xml_text.has(norm[k:n]):
                covered[k:n] = b"\x01" * (n - k)
            else:
                to_refine.append(j)
            continue
        if xml_text.has(chunk):
            covered[j:j + len(chunk)] = b"\x01" * len(chunk)
        else:
            to_refine.append(j)
    for j in to_refine:
        lo = max(start, j - WINDOW + 1)
        hi = min(n, j + CHUNK + WINDOW)
        for k in range(lo, hi - WINDOW + 1):
            if not all(covered[k:k + WINDOW]) and xml_text.has(norm[k:k + WINDOW]):
                covered[k:k + WINDOW] = b"\x01" * WINDOW
    return covered


def _lost_runs(covered, start):
    runs = []
    run_start = None
    for i in range(start, len(covered)):
        if not covered[i]:
            if run_start is None:
                run_start = i
        elif run_start is not None:
            runs.append((run_start, i))
            run_start = None
    if run_start is not None:
        runs.append((run_start, len(covered)))
    return [(a, b) for a, b in runs if b - a >= MIN_LOST]


_CITATION_RE = re.compile(r"[^\W\d_][.,;:)]?\d{1,3}(?:[,\-–]\d{1,3})*\b")


def _after_citation(text_before, owner_before):
    """
    True se o trecho vem logo depois de um número de citação (``…bacteriana,2``,
    ``…vancomicina.11``) ou de um sobrescrito.
    """
    if owner_before is not None and owner_before.tag == "sup":
        return True
    if owner_before is not None and "sup" in (owner_before.get("style") or ""):
        return True
    return bool(_CITATION_RE.search(text_before[-40:]))


def _refine(norm, a, b, xml_letters):
    """
    Ajusta as bordas de um trecho perdido ``norm[a:b]``: a cobertura por
    janelas não alcança trechos mantidos com menos de ``WINDOW`` letras
    junto às bordas (ex.: "Tuomi et al" antes de uma citação). Se o XML
    contém o início do trecho emendado no que vem depois dele (ou o que vem
    antes emendado no fim do trecho), essas letras foram mantidas.
    """
    limit = min(2 * WINDOW, b - a)
    if a == 0 and b == len(norm):
        # o bloco inteiro parece perdido: verifica se o XML tem o início e o
        # fim do bloco emendados (o miolo é que se perdeu)
        for p in range(min(WINDOW, b - a - MIN_LOST), 0, -1):
            prefix = norm[:p]
            if prefix not in xml_letters:
                continue
            for q in range(min(WINDOW, b - a - p - MIN_LOST), 0, -1):
                if p + q >= 10 and prefix + norm[b - q:] in xml_letters:
                    return p, b - q
        return a, b
    if b < len(norm):
        after = norm[b:b + WINDOW]
        for p in range(limit, 0, -1):
            if norm[a:a + p] + after in xml_letters:
                a += p
                break
    if a > 0:
        before = norm[max(0, a - WINDOW):a]
        for q in range(min(2 * WINDOW, b - a), 0, -1):
            if before + norm[b - q:b] in xml_letters:
                b -= q
                break
    return a, b


def _boundary(text, segments, starts, positions, inside, fallback):
    """
    Elemento na borda de um trecho perdido: o 1º caractere não-branco, entre
    o trecho e a letra vizinha, que pertence a outro elemento (ex.: o "15"
    em sobrescrito antes; o "*" de um link depois); senão, o elemento da
    letra vizinha (``fallback``, posição ou None).
    """
    for pos in positions:
        if text[pos].isspace():
            continue
        owner = _owner_at(segments, starts, pos)
        if owner is not inside:
            return owner, True
    if fallback is None:
        return None, False
    return _owner_at(segments, starts, fallback), True


def _block_spans(block, text, segments, norm, start, runs, xml_text):
    starts = [s[0] for s in segments]
    index = _letters_index(text)
    spans = []
    for a, b in runs:
        a, b = _refine(norm, a, b, xml_text.letters)
        if b - a < MIN_LOST:
            continue
        raw_start = index[a]
        raw_end = index[b - 1] + 1
        if a <= start and b >= len(norm) and start == 0:
            first = _owner_at(segments, starts, raw_start)
            key = f"whole {block.tag} ({_markup(first, block)})"
            if len(norm) < SHORT_BLOCK:
                # linha curta (título, autores, palavras-chave...): em geral
                # página de rosto que ficou fora do body
                spans.append({
                    "check": "short_text_lost",
                    "key": f"{block.tag} ({_markup(first, block)})",
                    "letters": b - a,
                    "lost": _clip(text, 300),
                    "html": " [[" + _clip(text, 300) + "]] ",
                    "xml": "",
                })
                continue
        else:
            # marcação vizinha: elemento entre o trecho e as letras ao redor
            prev_letter = index[a - 1] if a > 0 else None
            next_letter = index[b] if b < len(norm) else None
            previous, found = _boundary(
                text, segments, starts,
                range(raw_start - 1, (prev_letter if prev_letter is not None else -1), -1),
                _owner_at(segments, starts, raw_start), prev_letter,
            )
            before = _markup(previous, block) if found else "(start)"
            following, found = _boundary(
                text, segments, starts,
                range(raw_end, next_letter if next_letter is not None else len(text)),
                _owner_at(segments, starts, raw_end - 1), next_letter,
            )
            after = _markup(following, block) if found else "(end)"
            key = f"{before} → {after}"
            if _after_citation(text[:raw_start], previous):
                key += " [after citation number]"
        spans.append({
            "check": "text_lost",
            "key": key,
            "letters": b - a,
            "lost": _clip(text[raw_start:raw_end], 300),
            "html": (
                _clip(text[max(0, raw_start - CONTEXT):raw_start], CONTEXT, from_end=True)
                + " [[" + _clip(text[raw_start:raw_end], 300) + "]] "
                + _clip(text[raw_end:raw_end + CONTEXT], CONTEXT)
            ),
            "xml": xml_text.context(norm[max(0, a - WINDOW):a] if a - WINDOW >= start else ""),
        })
    return spans


def _anchor(norm, xml_body_letters):
    """
    Início do texto principal no bloco: o bloco tem ao menos 2 janelas de
    ``WINDOW`` letras e metade delas está no body do XML. Retorna a posição
    da 1ª janela presente ou None.
    """
    positions = range(0, len(norm) - WINDOW + 1, WINDOW)
    present = [j for j in positions if norm[j:j + WINDOW] in xml_body_letters]
    if len(present) >= 2 and len(present) * 2 >= len(positions):
        return present[0]
    return None


def text_analysis(html, xml):
    """
    Compara o texto do HTML inicial com o do XML.

    Retorna ``{"compared": bool, "total": letras comparadas, "lost":
    letras perdidas, "percent": % perdido, "spans": [trechos perdidos],
    "findings": [...]}``.
    """
    result = {"compared": False, "total": 0, "lost": 0, "percent": 0.0, "spans": [], "findings": []}
    html_body = html.find(".//body")
    xml_body = xml.find("body")
    if html_body is None or xml_body is None:
        return result
    xml_body_letters = normalize_letters("".join(xml_body.itertext()))
    if len(xml_body_letters) < 50:
        # body vazio ou quase: tratado por ``body_lost``
        return result
    xml_text = None
    started = False
    total = 0
    lost = 0
    spans = []
    blocks = list(_leaf_blocks(html_body)) or [html_body]
    for block in blocks:
        text, segments = _segments(block)
        norm = normalize_letters(_without_symbol_font(text, segments))
        if len(norm) < MIN_LOST:
            continue
        start = 0
        if not started:
            start = _anchor(norm, xml_body_letters)
            if start is None:
                continue
            started = True
            xml_text = _XmlText(xml)
        covered = _covered(norm, start, xml_text)
        runs = _lost_runs(covered, start)
        total += len(norm) - start
        if not runs:
            continue
        block_spans = _block_spans(
            block, _without_symbol_font(text, segments), segments, norm, start, runs, xml_text
        )
        lost += sum(s["letters"] for s in block_spans if s["check"] == "text_lost")
        spans.extend(block_spans)

    result.update(compared=started, total=total, lost=lost, spans=spans)
    result["percent"] = round(lost * 100 / total, 1) if total else 0.0
    if not started:
        result["findings"].append(finding("text_not_compared"))
        return result
    tally = _Tally()
    for span in spans:
        tally.add(span["check"], span["key"], example_text=f"HTML: {span['html']} | XML: {span['xml']}")
    result["findings"] = tally.findings()
    return result


def _in_symbol_font(node):
    while node is not None:
        if node.tag == "font" and "symbol" in (node.get("face") or "").lower():
            return True
        node = node.getparent()
    return False


def _without_symbol_font(text, segments):
    """
    Texto com o que está em fonte Symbol trocado por espaços (mesmo
    tamanho): "c" em Symbol é "χ" no XML, não uma perda.
    """
    symbol = [(a, b) for a, b, owner in segments if _in_symbol_font(owner)]
    if not symbol:
        return text
    chars = list(text)
    for a, b in symbol:
        chars[a:b] = " " * (b - a)
    return "".join(chars)


# ---------------------------------------------------------------------------
# Gravidade e avaliação completa
# ---------------------------------------------------------------------------

SEVERITY_CRITICAL = "critical"
SEVERITY_MAJOR = "major"
SEVERITY_MINOR = "minor"
SEVERITY_INFO = "info"
SEVERITIES = (SEVERITY_CRITICAL, SEVERITY_MAJOR, SEVERITY_MINOR, SEVERITY_INFO)
ATTENTION_SEVERITIES = (SEVERITY_CRITICAL, SEVERITY_MAJOR)

SEVERITY = {
    "step_failure": SEVERITY_CRITICAL,
    "conversion_blocked": SEVERITY_CRITICAL,
    "xml_unreadable": SEVERITY_CRITICAL,
    "body_lost": SEVERITY_CRITICAL,
    "text_lost": SEVERITY_CRITICAL,
    "refs_missing": SEVERITY_CRITICAL,
    "translation_missing": SEVERITY_CRITICAL,
    "table_wrap_empty": SEVERITY_CRITICAL,
    "fig_empty": SEVERITY_CRITICAL,
    "step_failure_after": SEVERITY_MAJOR,
    "conversion_exception": SEVERITY_MAJOR,
    "report_error": SEVERITY_MAJOR,
    "non_jats_element": SEVERITY_MAJOR,
    "xref_broken_rid": SEVERITY_MAJOR,
    "duplicate_id": SEVERITY_MAJOR,
    "refs_count_differs": SEVERITY_MAJOR,
    "refs_elem_vs_mixed": SEVERITY_MAJOR,
    "images_fewer_in_xml": SEVERITY_MAJOR,
    "front_in_body": SEVERITY_MAJOR,
    "xref_ref_type_invalid": SEVERITY_MINOR,
    "article_type_not_jats": SEVERITY_MINOR,
    "html_not_converted": SEVERITY_MINOR,
    "tables_fewer_in_xml": SEVERITY_MINOR,
    "zip_error": SEVERITY_MINOR,
    "no_event": SEVERITY_MINOR,
    "initial_html_unreadable": SEVERITY_MINOR,
    "short_text_lost": SEVERITY_MINOR,
    "no_html_text": SEVERITY_INFO,
    "text_not_compared": SEVERITY_INFO,
}


def severity(check):
    return SEVERITY.get(check, SEVERITY_MINOR)


def severity_rank(value):
    try:
        return SEVERITIES.index(value)
    except ValueError:
        return len(SEVERITIES)


def max_severity(findings):
    """Gravidade mais alta entre os achados (ou "" se não há achados)."""
    values = [severity(f["check"]) for f in findings]
    return min(values, key=severity_rank) if values else ""


def attention_points(findings):
    """Pontos de atenção: achados críticos e importantes."""
    return sum(1 for f in findings if severity(f["check"]) in ATTENTION_SEVERITIES)


# ---------------------------------------------------------------------------
# 6. Página de rosto repetida no body
# ---------------------------------------------------------------------------
# Os registros de parágrafo (tipo p) do site clássico trazem o texto
# completo, sem rótulos: página de rosto (título, autores, resumos,
# palavras-chave), corpo e anexos. O conversor só remove do body o que vem
# antes de uma seção de introdução reconhecida; sem ela, título, autores e
# resumos vão para o body e aparecem duas vezes (front e body).
# Compara o front do próprio XML com o body: não depende do HTML.

FRONT_PIECE = 40  # letras: trecho do front procurado no body
FRONT_HEAD = 3000  # letras: início do body (nomes curtos só são buscados aí)
FRONT_PARTS = (
    # (chave, xpath a partir do front, ignora <title>, só no início do body)
    ("article-title", ".//title-group/article-title", False, False),
    ("trans-title", ".//title-group//trans-title", False, False),
    ("abstract", ".//abstract", True, False),
    ("trans-abstract", ".//trans-abstract", True, False),
    ("kwd-group", ".//kwd-group", True, False),
    ("contrib-group", ".//contrib-group/contrib/name", False, True),
)


def _text_without_titles(node):
    """Texto de ``node`` sem os ``title`` (ex.: "Resumo", "Palavras-chave")."""
    from copy import deepcopy

    node = deepcopy(node)
    for title in node.findall(".//title"):
        title.getparent().remove(title)
    return " ".join(node.itertext())


def _front_body_pairs(xml):
    """(front, body) do artigo e de cada sub-article."""
    front, body = xml.find("front"), xml.find("body")
    if front is not None and body is not None:
        yield front, body
    for sub in xml.iter("sub-article"):
        front, body = sub.find("front-stub"), sub.find("body")
        if front is None:
            front = sub.find("front")
        if front is not None and body is not None:
            yield front, body


def front_in_body_findings(xml):
    """Partes do front (título, autores, resumos...) repetidas no body."""
    found = {}
    for front, body in _front_body_pairs(xml):
        body_letters = normalize_letters(" ".join(body.itertext()))
        if not body_letters:
            continue
        head = body_letters[:FRONT_HEAD]
        for key, xpath, skip_titles, head_only in FRONT_PARTS:
            nodes = front.findall(xpath)
            if key == "contrib-group":
                # nomes curtos: os dois primeiros autores no início do body,
                # como no HTML (prenome e sobrenome)
                names = [
                    " ".join(n.findtext(tag) or "" for tag in ("given-names", "surname"))
                    for n in nodes[:2]
                ]
                letters = [normalize_letters(n) for n in names]
                if letters and all(len(n) >= 6 and n in head for n in letters):
                    found.setdefault(key, "; ".join(" ".join(n.split()) for n in names))
                continue
            for node in nodes:
                text = _text_without_titles(node) if skip_titles else " ".join(node.itertext())
                letters = normalize_letters(text)
                if len(letters) < FRONT_PIECE:
                    continue
                piece = letters[:FRONT_PIECE]
                if piece in (head if head_only else body_letters):
                    found.setdefault(key, " ".join(text.split()))
                    break
    return [finding("front_in_body", key, example=example) for key, example in found.items()]


def evaluate(html, xml, data, journal_acron=""):
    """
    Avaliação de uma conversão com XML gerado.

    ``html``/``xml``: árvores (``html`` pode ser None, se o HTML inicial
    não está disponível); ``data``: contadores de ``HTMLXML``.
    Retorna ``{"findings", "text"}``.
    """
    findings = list(content_findings(data))
    findings.extend(structure_findings(xml))
    findings.extend(front_in_body_findings(xml))
    text = None
    if html is not None:
        findings.extend(html_findings(html, xml, journal_acron))
        text = text_analysis(html, xml)
        findings.extend(text["findings"])
    return {"findings": findings, "text": text}


# ---------------------------------------------------------------------------
# Textos (en / pt / es)
# ---------------------------------------------------------------------------

TEXTS = {
    f"group_{GROUP_FAILURE}": {"en": "failure", "pt": "falha", "es": "fallo"},
    f"group_{GROUP_CONTENT}": {"en": "content", "pt": "conteúdo", "es": "contenido"},
    f"group_{GROUP_STRUCTURE}": {"en": "XML structure", "pt": "estrutura do XML", "es": "estructura del XML"},
    f"group_{GROUP_HTML}": {"en": "HTML not converted", "pt": "HTML não convertido", "es": "HTML no convertido"},
    f"nature_{NATURE_BUG}": {"en": "converter bug", "pt": "bug do conversor", "es": "bug del conversor"},
    f"nature_{NATURE_MAPPING}": {"en": "missing mapping", "pt": "mapeamento ausente", "es": "mapeo ausente"},
    f"nature_{NATURE_DATA}": {"en": "source data", "pt": "dado de origem", "es": "dato de origen"},
    f"nature_{NATURE_CHECK}": {"en": "to be checked", "pt": "a verificar", "es": "a verificar"},
    "check_step_failure": {
        "en": "conversion step failed",
        "pt": "passo da conversão falhou",
        "es": "falló un paso de la conversión",
    },
    "desc_step_failure": {
        "en": "first step of the HTML->XML pipeline that raised an exception (step | exception | code location | message). The XML is generated from the last step that worked, so content may be lost. Open the link to get the ZIP with the output of each step",
        "pt": "primeiro passo do pipeline HTML->XML que levantou exceção (passo | exceção | local no código | mensagem). O XML é gerado a partir do último passo que funcionou, podendo perder conteúdo. Abra o link para obter o ZIP com a saída de cada passo",
        "es": "primer paso del pipeline HTML->XML que lanzó una excepción (paso | excepción | ubicación en el código | mensaje). El XML se genera a partir del último paso que funcionó, por lo que puede perder contenido. Abra el enlace para obtener el ZIP con la salida de cada paso",
    },
    "check_step_failure_after": {
        "en": "later step failed",
        "pt": "passo posterior falhou",
        "es": "falló un paso posterior",
    },
    "desc_step_failure_after": {
        "en": "step that failed after an earlier step had already failed; usually a consequence: fix the first failure first",
        "pt": "passo que falhou depois que um passo anterior já havia falhado; em geral é consequência: corrija antes a primeira falha",
        "es": "paso que falló después de que un paso anterior ya había fallado; en general es consecuencia: corrija primero el primer fallo",
    },
    "check_conversion_exception": {
        "en": "exception recorded by the converter",
        "pt": "exceção registrada pelo conversor",
        "es": "excepción registrada por el conversor",
    },
    "desc_conversion_exception": {
        "en": "exception recorded outside the body steps (e.g. processing a citation, dates, abstracts)",
        "pt": "exceção registrada fora dos passos do body (ex.: processamento de referência, datas, resumos)",
        "es": "excepción registrada fuera de los pasos del body (p. ej. procesamiento de referencia, fechas, resúmenes)",
    },
    "check_conversion_blocked": {
        "en": "conversion interrupted",
        "pt": "conversão interrompida",
        "es": "conversión interrumpida",
    },
    "desc_conversion_blocked": {
        "en": "the conversion raised an exception and no XML was produced (status BLOCKED)",
        "pt": "a conversão levantou exceção e não produziu XML (status BLOCKED)",
        "es": "la conversión lanzó una excepción y no produjo XML (estado BLOCKED)",
    },
    "check_report_error": {
        "en": "error in the conversion report",
        "pt": "erro no relatório da conversão",
        "es": "error en el informe de la conversión",
    },
    "desc_report_error": {
        "en": "the XML was generated, but the per-article evaluation failed; the counters of the article are not reliable",
        "pt": "o XML foi gerado, mas a avaliação do artigo falhou; os contadores do artigo não são confiáveis",
        "es": "el XML se generó, pero la evaluación del artículo falló; los contadores del artículo no son fiables",
    },
    "check_zip_error": {"en": "error saving the steps ZIP", "pt": "erro ao gravar o ZIP dos passos", "es": "error al guardar el ZIP de los pasos"},
    "desc_zip_error": {
        "en": "the ZIP with the output of each step could not be saved",
        "pt": "o ZIP com a saída de cada passo não pôde ser gravado",
        "es": "no se pudo guardar el ZIP con la salida de cada paso",
    },
    "check_no_event": {"en": "no conversion record", "pt": "sem registro da conversão", "es": "sin registro de la conversión"},
    "desc_no_event": {
        "en": "conversion with BLOCKED/PENDING status and no html_to_xml event in the article",
        "pt": "conversão com status BLOCKED/PENDING sem evento html_to_xml no artigo",
        "es": "conversión con estado BLOCKED/PENDING sin evento html_to_xml en el artículo",
    },
    "check_xml_unreadable": {"en": "generated XML unreadable", "pt": "XML gerado ilegível", "es": "XML generado ilegible"},
    "desc_xml_unreadable": {
        "en": "the generated XML file is missing or is not well-formed",
        "pt": "o arquivo XML gerado não existe ou não é bem formado",
        "es": "el archivo XML generado no existe o no está bien formado",
    },
    "check_body_lost": {"en": "body lost", "pt": "body perdido", "es": "body perdido"},
    "desc_body_lost": {
        "en": "empty body in the XML although the source has paragraphs",
        "pt": "body vazio no XML embora a base tenha parágrafos",
        "es": "body vacío en el XML aunque la base tiene párrafos",
    },
    "check_no_html_text": {"en": "no HTML text", "pt": "sem texto em HTML", "es": "sin texto en HTML"},
    "desc_no_html_text": {
        "en": "empty body and no paragraphs in the source (e.g. PDF-only article)",
        "pt": "body vazio e sem parágrafos na base (ex.: artigo só com PDF)",
        "es": "body vacío y sin párrafos en la base (p. ej. artículo solo con PDF)",
    },
    "check_refs_missing": {"en": "references lost", "pt": "referências perdidas", "es": "referencias perdidas"},
    "desc_refs_missing": {
        "en": "the source has references, but the XML has no mixed-citation",
        "pt": "a base tem referências, mas o XML não tem mixed-citation",
        "es": "la base tiene referencias, pero el XML no tiene mixed-citation",
    },
    "check_refs_count_differs": {
        "en": "number of references differs",
        "pt": "quantidade de referências difere",
        "es": "la cantidad de referencias difiere",
    },
    "desc_refs_count_differs": {
        "en": "number of references in the source differs from the number of mixed-citation in the XML",
        "pt": "quantidade de referências da base difere da de mixed-citation no XML",
        "es": "la cantidad de referencias de la base difiere de la de mixed-citation en el XML",
    },
    "check_refs_elem_vs_mixed": {
        "en": "element-citation x mixed-citation",
        "pt": "element-citation x mixed-citation",
        "es": "element-citation x mixed-citation",
    },
    "desc_refs_elem_vs_mixed": {
        "en": "number of element-citation differs from the number of mixed-citation",
        "pt": "quantidade de element-citation difere da de mixed-citation",
        "es": "la cantidad de element-citation difiere de la de mixed-citation",
    },
    "check_translation_missing": {"en": "translation missing", "pt": "tradução ausente", "es": "traducción ausente"},
    "desc_translation_missing": {
        "en": "the HTML has more languages (main + translations) than the XML (article + sub-article)",
        "pt": "o HTML tem mais idiomas (principal + traduções) que o XML (article + sub-article)",
        "es": "el HTML tiene más idiomas (principal + traducciones) que el XML (article + sub-article)",
    },
    "check_article_type_not_jats": {
        "en": "article-type outside JATS",
        "pt": "article-type fora do JATS",
        "es": "article-type fuera de JATS",
    },
    "desc_article_type_not_jats": {
        "en": "article-type with a value that is not in the JATS/SPS list: the section/type of the source has no mapping",
        "pt": "article-type com valor fora da lista JATS/SPS: o tipo/seção da base não tem mapeamento",
        "es": "article-type con valor fuera de la lista JATS/SPS: el tipo/sección de la base no tiene mapeo",
    },
    "check_images_fewer_in_xml": {"en": "fewer images in the XML", "pt": "menos imagens no XML", "es": "menos imágenes en el XML"},
    "desc_images_fewer_in_xml": {
        "en": "the HTML has more img than graphic + inline-graphic in the XML",
        "pt": "o HTML tem mais img que graphic + inline-graphic no XML",
        "es": "el HTML tiene más img que graphic + inline-graphic en el XML",
    },
    "check_tables_fewer_in_xml": {"en": "fewer tables in the XML", "pt": "menos tabelas no XML", "es": "menos tablas en el XML"},
    "desc_tables_fewer_in_xml": {
        "en": "the HTML has more table than table-wrap in the XML (layout tables are expected here)",
        "pt": "o HTML tem mais table que table-wrap no XML (tabelas de layout também aparecem aqui)",
        "es": "el HTML tiene más table que table-wrap en el XML (tablas de maquetación también aparecen aquí)",
    },
    "check_non_jats_element": {"en": "element outside JATS", "pt": "elemento fora do JATS", "es": "elemento fuera de JATS"},
    "desc_non_jats_element": {
        "en": "element that does not exist in JATS (usually HTML left over in the XML); the detail is the element name",
        "pt": "elemento que não existe no JATS (em geral HTML que sobrou no XML); o detalhe é o nome do elemento",
        "es": "elemento que no existe en JATS (en general HTML que quedó en el XML); el detalle es el nombre del elemento",
    },
    "check_xref_broken_rid": {"en": "xref to missing id", "pt": "xref para id inexistente", "es": "xref a id inexistente"},
    "desc_xref_broken_rid": {
        "en": "xref/@rid that does not match any @id in the XML; the detail is the ref-type",
        "pt": "xref/@rid que não corresponde a nenhum @id do XML; o detalhe é o ref-type",
        "es": "xref/@rid que no corresponde a ningún @id del XML; el detalle es el ref-type",
    },
    "check_xref_ref_type_invalid": {"en": "invalid ref-type", "pt": "ref-type inválido", "es": "ref-type inválido"},
    "desc_xref_ref_type_invalid": {
        "en": "xref without ref-type or with a value that is not in JATS",
        "pt": "xref sem ref-type ou com valor fora do JATS",
        "es": "xref sin ref-type o con valor fuera de JATS",
    },
    "check_duplicate_id": {"en": "duplicate id", "pt": "id duplicado", "es": "id duplicado"},
    "desc_duplicate_id": {
        "en": "the same @id in more than one element; the detail is the element of the first occurrence",
        "pt": "o mesmo @id em mais de um elemento; o detalhe é o elemento da 1ª ocorrência",
        "es": "el mismo @id en más de un elemento; el detalle es el elemento de la 1.ª ocurrencia",
    },
    "check_table_wrap_empty": {"en": "empty table-wrap", "pt": "table-wrap vazio", "es": "table-wrap vacío"},
    "desc_table_wrap_empty": {
        "en": "table-wrap without table, graphic or alternatives",
        "pt": "table-wrap sem table, graphic ou alternatives",
        "es": "table-wrap sin table, graphic o alternatives",
    },
    "check_fig_empty": {"en": "fig without image", "pt": "fig sem imagem", "es": "fig sin imagen"},
    "desc_fig_empty": {
        "en": "fig without graphic, alternatives or media",
        "pt": "fig sem graphic, alternatives ou media",
        "es": "fig sin graphic, alternatives o media",
    },
    "check_html_not_converted": {
        "en": "HTML without match in the XML",
        "pt": "HTML sem correspondente no XML",
        "es": "HTML sin correspondencia en el XML",
    },
    "desc_html_not_converted": {
        "en": "link, anchor or image of the initial HTML not found in the XML (same rules as the article report); the detail is the pattern, e.g. a[href=#…], a[name=tN], img[src=journal-dir]",
        "pt": "link, âncora ou imagem do HTML inicial não encontrado no XML (mesmas regras do relatório do artigo); o detalhe é o padrão, ex.: a[href=#…], a[name=tN], img[src=journal-dir]",
        "es": "enlace, ancla o imagen del HTML inicial no encontrado en el XML (mismas reglas del informe del artículo); el detalle es el patrón, p. ej. a[href=#…], a[name=tN], img[src=journal-dir]",
    },
    "check_initial_html_unreadable": {
        "en": "initial HTML unreadable",
        "pt": "HTML inicial ilegível",
        "es": "HTML inicial ilegible",
    },
    "desc_initial_html_unreadable": {
        "en": "the initial HTML (structured in body/back) is missing or not well-formed; the HTML comparison was not done",
        "pt": "o HTML inicial (estruturado em body/back) não existe ou não é bem formado; a comparação com o HTML não foi feita",
        "es": "el HTML inicial (estructurado en body/back) no existe o no está bien formado; no se hizo la comparación con el HTML",
    },
    "check_text_lost": {"en": "text lost", "pt": "texto perdido", "es": "texto perdido"},
    "desc_text_lost": {
        "en": "passage of the main text of the HTML that is not in the XML; the detail is the HTML markup before → after the lost passage (e.g. text → a[href=#…]/span[sup]), which groups losses with the same cause; the example shows the lost passage between [[ ]] in the HTML and the same point in the XML",
        "pt": "trecho do texto principal do HTML que não está no XML; o detalhe é a marcação HTML antes → depois do trecho perdido (ex.: text → a[href=#…]/span[sup]), que agrupa perdas com a mesma causa; o exemplo mostra o trecho perdido entre [[ ]] no HTML e o mesmo ponto no XML",
        "es": "fragmento del texto principal del HTML que no está en el XML; el detalle es el marcado HTML antes → después del fragmento perdido (p. ej. text → a[href=#…]/span[sup]), que agrupa pérdidas con la misma causa; el ejemplo muestra el fragmento perdido entre [[ ]] en el HTML y el mismo punto en el XML",
    },
    "check_short_text_lost": {
        "en": "short line lost",
        "pt": "linha curta perdida",
        "es": "línea corta perdida",
    },
    "desc_short_text_lost": {
        "en": "short block of the HTML (title, authors, keywords, correspondence...) entirely missing in the XML; usually front matter that was left out of the body: check whether it is in the metadata",
        "pt": "bloco curto do HTML (título, autores, palavras-chave, correspondência...) ausente por inteiro no XML; em geral página de rosto que ficou fora do body: verifique se está nos metadados",
        "es": "bloque corto del HTML (título, autores, palabras clave, correspondencia...) ausente por completo en el XML; en general portada que quedó fuera del body: verifique si está en los metadatos",
    },
    "check_front_in_body": {
        "en": "front matter repeated in the body",
        "pt": "página de rosto repetida no body",
        "es": "portada repetida en el body",
    },
    "desc_front_in_body": {
        "en": "part of the front (title, authors, abstracts, keywords) also appears in the body, so it is shown twice. The paragraph records of the classic site contain the whole unlabeled text (front, body and back) and the converter only removes what comes before a recognized introduction section. Fix in the converter (scielo_classic_website) and reprocess",
        "pt": "parte do front (título, autores, resumos, palavras-chave) aparece também no body e é exibida duas vezes. Os registros de parágrafo do site clássico contêm o texto inteiro sem rótulos (front, body e back) e o conversor só remove o que vem antes de uma seção de introdução reconhecida. Corrigir no conversor (scielo_classic_website) e reprocessar",
        "es": "parte del front (título, autores, resúmenes, palabras clave) aparece también en el body y se muestra dos veces. Los registros de párrafo del sitio clásico contienen el texto completo sin etiquetas (front, body y back) y el conversor solo elimina lo que viene antes de una sección de introducción reconocida. Corregir en el conversor (scielo_classic_website) y reprocesar",
    },
    "check_text_not_compared": {
        "en": "text not compared",
        "pt": "texto não comparado",
        "es": "texto no comparado",
    },
    "desc_text_not_compared": {
        "en": "no passage of the HTML body was found in the XML body, so the start of the main text could not be located; check the article",
        "pt": "nenhum trecho do body do HTML foi encontrado no body do XML, então o início do texto principal não pôde ser localizado; verifique o artigo",
        "es": "ningún fragmento del body del HTML se encontró en el body del XML, así que no se pudo localizar el inicio del texto principal; verifique el artículo",
    },
    "severity": {"en": "Severity", "pt": "Gravidade", "es": "Gravedad"},
    f"severity_{SEVERITY_CRITICAL}": {"en": "critical", "pt": "crítico", "es": "crítico"},
    f"severity_{SEVERITY_MAJOR}": {"en": "major", "pt": "importante", "es": "importante"},
    f"severity_{SEVERITY_MINOR}": {"en": "minor", "pt": "menor", "es": "menor"},
    f"severity_{SEVERITY_INFO}": {"en": "information", "pt": "informação", "es": "información"},
    f"severity_desc_{SEVERITY_CRITICAL}": {
        "en": "content lost or conversion failed",
        "pt": "conteúdo perdido ou falha na conversão",
        "es": "contenido perdido o fallo en la conversión",
    },
    f"severity_desc_{SEVERITY_MAJOR}": {
        "en": "defective XML (invalid elements, broken links, duplicate ids)",
        "pt": "XML defeituoso (elementos inválidos, ligações quebradas, ids duplicados)",
        "es": "XML defectuoso (elementos inválidos, enlaces rotos, ids duplicados)",
    },
    f"severity_desc_{SEVERITY_MINOR}": {
        "en": "values without mapping, links/anchors of the HTML without match",
        "pt": "valores sem mapeamento, links/âncoras do HTML sem correspondente",
        "es": "valores sin mapeo, enlaces/anclas del HTML sin correspondencia",
    },
    f"severity_desc_{SEVERITY_INFO}": {
        "en": "expected differences or not verifiable",
        "pt": "diferenças esperadas ou não verificáveis",
        "es": "diferencias esperadas o no verificables",
    },
}


def t(key, lang):
    entry = TEXTS[key]
    return entry.get(lang) or entry["en"]


def category_hash(check, key):
    """Identificador estável de uma categoria (verificação + chave)."""
    import hashlib

    return hashlib.sha1(f"{check}|{key or ''}".encode("utf-8")).hexdigest()
