"""Pure checks for SPS 1.10 change packages (issue 1113).

Packtools remains responsible for DTD/SPS validation. These checks cannot verify
PDF contents, watermarks, editorial wording, or the scientific scope of a change.
A corrected original DOI must be resolved to the published PID by orchestration;
it is deliberately not treated as a new notice DOI here.
"""

import posixpath
import re
from urllib.parse import unquote, urlsplit

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

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
        raise ValidationError(_("An article XML is required."), code="missing_article")

    return root


def _documents(root):
    return [root] + root.findall(".//sub-article[@article-type='translation']")


def _meta(document):
    path = "front/article-meta" if document.tag == "article" else "front-stub"
    meta = document.find(path)
    if meta is None:
        raise ValidationError(_("Missing article metadata."), code="missing_metadata")

    return meta


def validate_change_pair(change_type, original_xml, notice_xml):
    """Check the submitted pair; SPS rules and editorial review run afterwards."""
    if change_type not in CHANGE_TYPES:
        raise ValidationError(_("Unsupported change type."), code="change_type")

    original = XMLWithPre("", _root(original_xml))
    notice = XMLWithPre("", _root(notice_xml))
    notice_type, reverse, forward = CHANGE_TYPES[change_type][:3]
    original_dois = {
        normalize_doi(item["value"])
        for item in original.article_doi_with_lang
        if item["value"]
    }
    notice_dois = {
        normalize_doi(item["value"])
        for item in notice.article_doi_with_lang
        if item["value"]
    }
    if not original.main_doi or not notice.main_doi:
        raise ValidationError(_("A document DOI is required."), code="missing_doi")
    if original_dois & notice_dois:
        raise ValidationError(
            _("Original and notice must have distinct DOIs."), code="same_doi"
        )
    if notice.xmltree.get("article-type") != notice_type:
        raise ValidationError(_("Incorrect notice article-type."), code="notice_type")

    original_languages = set(original.langs)
    notice_languages = set(notice.langs)

    for source, target, languages, relation_type in (
        (original, notice, original_languages, forward),
        (notice, original, notice_languages, reverse),
    ):
        target_dois = {
            item["lang"]: normalize_doi(item["value"])
            for item in target.article_doi_with_lang
            if item["value"]
        }
        relations = list(source.related_items)
        for language in languages:
            expected_doi = target_dois.get(language, normalize_doi(target.main_doi))
            if not any(
                item.get("related-article-type") == relation_type
                and item.get("ext-link-type") == "doi"
                and item.get("parent_lang") == language
                and normalize_doi(item.get("href")) == expected_doi
                for item in relations
            ):
                raise ValidationError(
                    _("Missing direct DOI relationship: %s.") % relation_type,
                    code="missing_relationship",
                )

    if change_type != "erratum" and not original_languages <= notice_languages:
        raise ValidationError(
            _("The notice must cover all original languages."),
            code="missing_translation",
        )


def _package_path(value):
    """Only unambiguous relative ZIP paths; reject traversal, URLs and drives."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValidationError(_("Unsafe package path."), code="unsafe_path")

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
        raise ValidationError(_("Unsafe package path."), code="unsafe_path")

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
                    _("A translation needs a language for its PDF."),
                    code="missing_translation",
                )
            suffix = "" if document is root else "-" + language
            required = [_package_path(basename + suffix + ".pdf")]

        for name in required:
            path = posixpath.join(directory, name)
            if not name.lower().endswith(".pdf") or path not in available:
                raise ValidationError(
                    _("Missing document PDF: %s.") % path, code="missing_pdf"
                )
