"""Pure checks for SPS 1.10 change packages (issue 1113).

Packtools remains responsible for DTD/SPS validation. These checks cannot verify
PDF contents, watermarks, editorial wording, or the scientific scope of a change.
A corrected original DOI must be resolved to the published PID by orchestration;
it is deliberately not treated as a new notice DOI here.
"""

import posixpath
import re
from collections import Counter
from copy import deepcopy
from datetime import date
from urllib.parse import unquote, urlsplit

from django.core.exceptions import ValidationError

XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
CHANGE_TYPES = {
    "erratum": ("correction", "corrected-article", "correction-forward", "corrected"),
    "addendum": ("addendum", "addended-article", "addendum", "corrected"),
    "retraction": (
        "retraction",
        "retracted-article",
        "retraction-forward",
        "retracted",
    ),
    "partial-retraction": (
        "partial-retraction",
        "retracted-article",
        "partial-retraction",
        "retracted",
    ),
}


def normalize_doi(value):
    """Return a bare, lowercase DOI, accepting DOI labels and resolver URLs."""
    value = (value or "").strip()
    value = re.sub(r"^doi\s*:\s*", "", value, flags=re.I)
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    return value.strip().lower()


def _root(xml):
    root = xml.getroot() if hasattr(xml, "getroot") else xml
    if root is None or root.tag != "article":
        raise ValidationError("An article XML is required.", code="missing_article")
    return root


def _documents(root):
    return [root] + root.findall(".//sub-article[@article-type='translation']")


def _meta(document):
    path = "front/article-meta" if document.tag == "article" else "front-stub"
    meta = document.find(path)
    if meta is None:
        raise ValidationError("Missing article metadata.", code="missing_metadata")
    return meta


def _doi(root):
    dois = {
        normalize_doi("".join(node.itertext()))
        for node in _meta(root).findall("article-id[@pub-id-type='doi']")
    }
    if len(dois) != 1 or not all(re.fullmatch(r"10\.\d{4,9}/\S+", doi) for doi in dois):
        raise ValidationError("A single document DOI is required.", code="missing_doi")
    return dois.pop()


def _languages(root):
    return {doc.get(XML_LANG) for doc in _documents(root) if doc.get(XML_LANG)}


def _declared_dois(root):
    return {
        doi
        for document in _documents(root)
        for node in _meta(document).findall("article-id[@pub-id-type='doi']")
        if (doi := normalize_doi("".join(node.itertext())))
    }


def _relationships(root, relation_type, counterpart):
    main_doi = _doi(counterpart)
    targets = {
        document.get(XML_LANG): _doi(document)
        for document in _documents(counterpart)
        if _meta(document).find("article-id[@pub-id-type='doi']") is not None
    }
    ids = Counter(node.get("id") for node in root.iter() if node.get("id"))
    for document in _documents(root):
        target = targets.get(document.get(XML_LANG), main_doi)
        relations = _meta(document).findall("related-article")
        matches = [
            node
            for node in relations
            if (
                node.get("related-article-type") == relation_type
                and node.get("ext-link-type") == "doi"
                and normalize_doi(node.get(XLINK_HREF)) == target
            )
        ]
        if not matches:
            raise ValidationError(
                "Missing direct DOI relationship: %s." % relation_type,
                code="missing_relationship",
            )
        for node in matches:
            if not node.get("id") or ids[node.get("id")] != 1:
                raise ValidationError(
                    "Relationship IDs must be unique.", code="relationship_id"
                )
            if len(node) or "".join(node.itertext()).strip():
                raise ValidationError(
                    "Relationships must be empty elements.", code="relationship_text"
                )


def _history(root, date_type):
    dates = _meta(root).findall("history/date[@date-type='%s']" % date_type)
    if not dates:
        raise ValidationError(
            "Missing %s history date." % date_type, code="missing_history"
        )
    for node in dates:
        try:
            values = [
                node.findtext(part, "").strip() for part in ("year", "month", "day")
            ]
            if not all(re.fullmatch(r"[0-9]+", value) for value in values):
                raise ValueError
            date(*[int(value) for value in values])
        except (ValueError, TypeError, OverflowError):
            raise ValidationError("Invalid history date.", code="invalid_history")


def _text(value):
    return " ".join((value or "").split())


def _xml_text(node):
    """Normalized prose, retaining spaces between adjacent inline elements."""
    if node is None:
        return ""
    blocks = {
        "body",
        "back",
        "sec",
        "p",
        "title",
        "list",
        "list-item",
        "ref-list",
        "ref",
    }

    def parts(element):
        if element.text and (element.text.strip() or "\n" not in element.text):
            yield element.text
        for child in element:
            if isinstance(child.tag, str):
                if child.tag in blocks:
                    yield " "
                yield from parts(child)
                if child.tag in blocks:
                    yield " "
            if child.tail and (child.tail.strip() or "\n" not in child.tail):
                yield child.tail

    return _text("".join(parts(node)))


def _signature(node):
    """Compare XML semantics, not attribute order or pretty-print indentation."""
    if node is None:
        return None
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        _text(node.text),
        _xml_text(node),
        tuple(
            (_signature(child), _text(child.tail))
            for child in node
            if isinstance(child.tag, str)
        ),
    )


def _without_citations(node):
    if node is None:
        return None
    node = deepcopy(node)
    for child in list(node.iter()):
        if child.tag == "ref-list" or (
            child.tag == "xref" and child.get("ref-type") == "bibr"
        ):
            parent = child.getparent()
            if parent is not None:
                previous = child.getprevious()
                if previous is None:
                    parent.text = (parent.text or "") + (child.tail or "")
                else:
                    previous.tail = (previous.tail or "") + (child.tail or "")
                parent.remove(child)
    return node


def _addendum_front(document, old):
    """Ignore only new addendum links/corrected dates, never prior metadata."""
    path = "front" if document.tag == "article" else "front-stub"
    front = deepcopy(document.find(path))
    meta = front.find("article-meta") if document.tag == "article" else front
    previous = _meta(old)
    for selector in (
        "related-article[@related-article-type='addendum']",
        "history/date[@date-type='corrected']",
    ):
        retained = Counter(_signature(node) for node in previous.findall(selector))
        for node in list(meta.findall(selector)):
            signature = _signature(node)
            if retained[signature]:
                retained[signature] -= 1
            else:
                node.getparent().remove(node)
    if previous.find("history") is None:
        history = meta.find("history")
        if (
            history is not None
            and not len(history)
            and not history.attrib
            and not _text(history.text)
        ):
            meta.remove(history)
    return front


def _retraction_titles(document):
    """Group normalized titles by kind and title language, not translation order."""
    titles = {}
    group = _meta(document).find("title-group")
    if group is not None:
        for node in group.findall("article-title"):
            titles.setdefault(("article-title", document.get(XML_LANG)), []).append(
                _xml_text(node)
            )
        for translation in group.findall("trans-title-group"):
            for node in translation.findall("trans-title"):
                titles.setdefault(
                    ("trans-title", translation.get(XML_LANG)), []
                ).append(_xml_text(node))
    return titles


def _protect_content(change_type, original, published):
    """Protect published content, including structural retraction title additions.

    Each published title must remain identifiable with added normalized text.
    This is structural comparison only, not editorial validation of the warning
    term or its language; that remains mandatory manual QA.
    """
    previous = {doc.get(XML_LANG): doc for doc in _documents(published)}
    for document in _documents(original):
        old = previous.get(document.get(XML_LANG))
        if old is None:
            continue
        if change_type in {"retraction", "partial-retraction"}:
            current_titles = _retraction_titles(document)
            for key, titles in _retraction_titles(old).items():
                for title in titles:
                    if not any(
                        title != current and title in current
                        for current in current_titles.get(key, [])
                    ):
                        raise ValidationError(
                            "Retraction titles must preserve published titles with added text.",
                            code="changed_title",
                        )
        elif change_type == "addendum":
            path = "front" if document.tag == "article" else "front-stub"
            if _signature(_addendum_front(document, old)) != _signature(old.find(path)):
                raise ValidationError(
                    "An addendum must preserve published metadata.",
                    code="changed_content",
                )
            for section in ("body", "back"):
                if _signature(document.find(section)) != _signature(old.find(section)):
                    raise ValidationError(
                        "An addendum must preserve published body/back.",
                        code="changed_content",
                    )
            assets = {"graphic", "inline-graphic", "media", "supplementary-material"}
            old_assets = [_signature(node) for node in old.iter() if node.tag in assets]
            new_assets = [
                _signature(node) for node in document.iter() if node.tag in assets
            ]
            if old_assets != new_assets:
                raise ValidationError(
                    "An addendum must preserve published assets.",
                    code="changed_content",
                )
        elif change_type == "erratum":
            # Bibliographic citations/references may be corrected, not body text or assets.
            for section in ("body", "back"):
                if _signature(_without_citations(document.find(section))) != _signature(
                    _without_citations(old.find(section))
                ):
                    raise ValidationError(
                        "An erratum cannot rewrite published content.",
                        code="changed_content",
                    )


def validate_change_pair(change_type, original_xml, notice_xml, published_xml=None):
    """Raise ValidationError for a mechanically invalid pair; otherwise return None.

    Without published_xml, preservation of earlier content, type and languages
    cannot be established. How much a partial retraction removes remains human
    QA: no unchanged block, percentage or textual similarity is required.
    """
    if change_type not in CHANGE_TYPES:
        raise ValidationError("Unsupported change type.", code="change_type")
    original, notice = _root(original_xml), _root(notice_xml)
    notice_type, reverse, forward, date_type = CHANGE_TYPES[change_type]
    original_doi = _doi(original)
    _doi(notice)
    if _declared_dois(original) & _declared_dois(notice):
        raise ValidationError(
            "Original and notice must have distinct DOIs.", code="same_doi"
        )
    if notice.get("article-type") != notice_type:
        raise ValidationError("Incorrect notice article-type.", code="notice_type")
    if not original.get("article-type"):
        raise ValidationError(
            "The original must retain its article-type.", code="original_type"
        )
    _relationships(original, forward, notice)
    _relationships(notice, reverse, original)
    _history(original, date_type)
    if change_type != "erratum" and not _languages(original) <= _languages(notice):
        raise ValidationError(
            "The notice must cover all original languages.", code="missing_translation"
        )
    if change_type in {"retraction", "partial-retraction"}:
        notices = {doc.get(XML_LANG): doc for doc in _documents(notice)}
        for document in _documents(original):
            body_text = _xml_text(document.find("body"))
            notice_document = notices.get(document.get(XML_LANG))
            notice_text = (
                _xml_text(notice_document.find("body"))
                if notice_document is not None
                else ""
            )
            if change_type == "retraction":
                if document.find("back") is not None:
                    raise ValidationError(
                        "A total retraction cannot retain back.", code="retained_back"
                    )
                if not body_text or body_text != notice_text:
                    raise ValidationError(
                        "The retracted body must contain only the notice text, not the published body.",
                        code="retained_body",
                    )
            elif not body_text or body_text == notice_text:
                raise ValidationError(
                    "A partial retraction must retain original content, not only the notice.",
                    code="replaced_content",
                )
    if published_xml is not None:
        published = _root(published_xml)
        published_doi = _doi(published)
        if original.get("article-type") != published.get("article-type"):
            raise ValidationError(
                "The original article-type changed.", code="original_type"
            )
        if not _languages(published) <= _languages(original):
            raise ValidationError(
                "Published languages cannot be removed.", code="missing_translation"
            )
        if change_type != "erratum" and published_doi != original_doi:
            raise ValidationError("The published DOI changed.", code="changed_doi")
        if _declared_dois(published) & _declared_dois(notice):
            raise ValidationError(
                "The notice cannot reuse the published DOI.", code="same_doi"
            )
        _protect_content(change_type, original, published)


def _package_path(value):
    """Only unambiguous relative ZIP paths; reject traversal, URLs and drives."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValidationError("Unsafe package path.", code="unsafe_path")
    decoded = unquote(value)
    if (
        decoded.startswith("/")
        or urlsplit(decoded).scheme
        or urlsplit(decoded).netloc
        or any(part == ".." for part in decoded.split("/"))
        or "\\" in decoded
        or "\x00" in decoded
        or "?" in decoded
        or "#" in decoded
    ):
        raise ValidationError("Unsafe package path.", code="unsafe_path")
    return posixpath.normpath(decoded)


def require_document_pdfs(xml, filenames, xml_filename):
    """Require each language's PDF in the ZIP, never infer PDF visual compliance.

    Explicit self-uri paths are relative to the XML, and take precedence over
    conventional names. No cross-document basename matching is performed.
    """
    root = _root(xml)
    xml_path = _package_path(xml_filename)
    available = {_package_path(name) for name in filenames}
    directory = posixpath.dirname(xml_path)
    basename = posixpath.splitext(posixpath.basename(xml_path))[0]
    for document in _documents(root):
        refs = _meta(document).findall("self-uri[@content-type='pdf']")
        if refs:
            required = [_package_path(node.get(XLINK_HREF)) for node in refs]
        else:
            language = document.get(XML_LANG)
            if document is not root and not language:
                raise ValidationError(
                    "A translation needs a language for its PDF.",
                    code="missing_translation",
                )
            suffix = "" if document is root else "-" + language
            required = [_package_path(basename + suffix + ".pdf")]
        for name in required:
            path = posixpath.join(directory, name)
            if not name.lower().endswith(".pdf") or path not in available:
                raise ValidationError(
                    "Missing document PDF: %s." % path, code="missing_pdf"
                )
