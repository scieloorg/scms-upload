"""Pure package validation tests: no database, filesystem PDFs or orchestration."""

from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError
from lxml import etree

from upload.validation.article_changes import (
    normalize_doi,
    require_document_pdfs,
    validate_change_pair,
)

XLINK = "{http://www.w3.org/1999/xlink}href"
LANG = "{http://www.w3.org/XML/1998/namespace}lang"
TYPES = {
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


def article(doi, article_type="research-article"):
    root = etree.fromstring(
        b'<article xmlns:xlink="http://www.w3.org/1999/xlink" xml:lang="pt">'
        b'<front><article-meta><article-id pub-id-type="doi"/>'
        b"<title-group><article-title>A descriptive title</article-title></title-group>"
        b"</article-meta></front><body><sec><p>Published paragraph.</p>"
        b"<list><list-item><p>Nested published content.</p></list-item></list>"
        b'</sec></body><back><ref-list><ref id="ref1"><mixed-citation>'
        b"A bibliographic reference.</mixed-citation></ref></ref-list></back></article>"
    )
    root.set("article-type", article_type)
    root.find("front/article-meta/article-id").text = doi
    return root


def metadata(document):
    return (
        document.find("front/article-meta")
        if document.tag == "article"
        else document.find("front-stub")
    )


def translate(root, language="en"):
    translation = etree.SubElement(
        root, "sub-article", {"article-type": "translation", LANG: language}
    )
    stub = etree.SubElement(translation, "front-stub")
    title_group = etree.SubElement(stub, "title-group")
    etree.SubElement(title_group, "article-title").text = "An English translated title"
    translation.append(deepcopy(root.find("body")))
    return translation


def relate(document, relation_type, target, identifier):
    return etree.SubElement(
        metadata(document),
        "related-article",
        {
            "id": identifier,
            XLINK: target,
            "ext-link-type": "doi",
            "related-article-type": relation_type,
        },
    )


def pair(kind, translated=False, translated_dois=False):
    notice_type, reverse, forward, date_type = TYPES[kind]
    published = article("10.1234/original")
    if translated:
        translation = translate(published)
        if translated_dois:
            etree.SubElement(
                metadata(translation), "article-id", {"pub-id-type": "doi"}
            ).text = "10.1234/original-en"
    if kind in {"retraction", "partial-retraction"}:
        for document in [published] + published.findall("sub-article"):
            for language, title in (
                ("es", "Un título en español"),
                ("fr", "Un titre en français"),
            ):
                group = etree.SubElement(
                    metadata(document).find("title-group"),
                    "trans-title-group",
                    {LANG: language},
                )
                etree.SubElement(group, "trans-title").text = title
    original = deepcopy(published)
    if kind in {"retraction", "partial-retraction"}:
        warnings = {
            "retraction": {
                "pt": "ARTIGO RETRATADO",
                "en": "RETRACTED ARTICLE",
                "es": "ARTÍCULO RETRACTADO",
                "fr": "ARTICLE RÉTRACTÉ",
            },
            "partial-retraction": {
                "pt": "ARTIGO PARCIALMENTE RETRATADO",
                "en": "PARTIALLY RETRACTED ARTICLE",
                "es": "ARTÍCULO PARCIALMENTE RETRACTADO",
                "fr": "ARTICLE PARTIELLEMENT RÉTRACTÉ",
            },
        }[kind]
        for document in [original] + original.findall("sub-article"):
            group = metadata(document).find("title-group")
            title = group.find("article-title")
            title.text += " — " + warnings[document.get(LANG)]
            for translation in group.findall("trans-title-group"):
                translation.find("trans-title").text += (
                    " — " + warnings[translation.get(LANG)]
                )
    notice = article("10.1234/notice", notice_type)
    notice.find("body/sec/p").text = "Editorial explanation of the change."
    if kind == "retraction":
        notice.find("body").clear()
        etree.SubElement(
            notice.find("body"), "p"
        ).text = "Editorial explanation of the retraction."
    if translated:
        translation = translate(notice)
        if translated_dois:
            etree.SubElement(
                metadata(translation), "article-id", {"pub-id-type": "doi"}
            ).text = "10.1234/notice-en"
        if kind == "retraction":
            translation.find("body/p").text = "Editorial explanation in English."
    for root, relationship, target in (
        (original, forward, "10.1234/notice"),
        (notice, reverse, "10.1234/original"),
    ):
        documents = [root] + root.findall("sub-article")
        for index, document in enumerate(documents):
            document_target = target + "-en" if index and translated_dois else target
            relate(document, relationship, document_target, "related-%s" % index)
    history = etree.SubElement(metadata(original), "history")
    approval = etree.SubElement(history, "date", {"date-type": date_type})
    for name, value in (("day", "28"), ("month", "2"), ("year", "2025")):
        etree.SubElement(approval, name).text = value
    if kind == "retraction":
        for document, notice_document in zip(
            [original] + original.findall("sub-article"),
            [notice] + notice.findall("sub-article"),
        ):
            document.replace(
                document.find("body"), deepcopy(notice_document.find("body"))
            )
            back = document.find("back")
            if back is not None:
                document.remove(back)
    return original, notice, published


@pytest.mark.parametrize(
    "value",
    [
        "10.1234/AbC",
        " DOI: 10.1234/ABC ",
        "https://doi.org/10.1234/ABC",
        "HTTP://DX.DOI.ORG/10.1234/ABC",
        "doi: https://doi.org/10.1234/ABC",
    ],
)
def test_normalize_doi(value):
    assert normalize_doi(value) == "10.1234/abc"


@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("translated", [False, True])
def test_valid_pairs(kind, translated):
    original, notice, published = pair(kind, translated)
    assert (
        validate_change_pair(kind, original, etree.ElementTree(notice), published)
        is None
    )


@pytest.mark.parametrize("kind", TYPES)
def test_translations_with_distinct_dois(kind):
    original, notice, published = pair(kind, translated=True, translated_dois=True)
    assert validate_change_pair(kind, original, notice, published) is None


@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("side", [0, 1])
def test_translation_relationship_cannot_target_main_when_own_doi_declared(kind, side):
    documents = pair(kind, translated=True, translated_dois=True)
    counterpart = documents[1 - side]
    documents[side].find("sub-article/front-stub/related-article").set(
        XLINK, metadata(counterpart).find("article-id").text
    )
    with pytest.raises(ValidationError, match="relationship"):
        validate_change_pair(kind, *documents)


@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("notice_language", ["pt", "en"])
def test_notice_doi_cannot_collide_with_original_translation(kind, notice_language):
    original, notice, published = pair(kind, translated=True, translated_dois=True)
    document = notice if notice_language == "pt" else notice.find("sub-article")
    metadata(document).find("article-id").text = "HTTPS://DOI.ORG/10.1234/ORIGINAL-EN"
    with pytest.raises(ValidationError, match="distinct"):
        validate_change_pair(kind, original, notice, published)


@pytest.mark.parametrize("kind", TYPES)
def test_translation_may_explicitly_reuse_its_own_main_doi(kind):
    original, notice, published = pair(kind, translated=True)
    for root in (original, notice, published):
        etree.SubElement(
            metadata(root.find("sub-article")), "article-id", {"pub-id-type": "doi"}
        ).text = (metadata(root).find("article-id").text)
    assert validate_change_pair(kind, original, notice, published) is None


def test_single_language_erratum_falls_back_to_notice_main_with_original_own_doi():
    original, notice, published = pair("erratum", translated=True, translated_dois=True)
    notice.remove(notice.find("sub-article"))
    original.find("sub-article/front-stub/related-article").set(XLINK, "10.1234/notice")
    assert validate_change_pair("erratum", original, notice, published) is None


@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("side", [0, 1])
def test_wrong_relationship_direction(kind, side):
    documents = pair(kind)
    relation = metadata(documents[side]).find("related-article")
    relation.set("related-article-type", "unrelated")
    with pytest.raises(ValidationError, match="relationship"):
        validate_change_pair(kind, *documents[:2])


@pytest.mark.parametrize("kind", TYPES)
def test_equal_dois(kind):
    original, notice, _ = pair(kind)
    metadata(notice).find("article-id").text = "HTTPS://DOI.ORG/10.1234/ORIGINAL"
    with pytest.raises(ValidationError, match="distinct"):
        validate_change_pair(kind, original, notice)


@pytest.mark.parametrize("side", [0, 1])
def test_missing_doi(side):
    documents = pair("erratum")
    metadata(documents[side]).remove(metadata(documents[side]).find("article-id"))
    with pytest.raises(ValidationError, match="DOI"):
        validate_change_pair("erratum", *documents[:2])


def test_missing_original():
    with pytest.raises(ValidationError, match="article XML"):
        validate_change_pair("erratum", None, article("10.1234/notice"))


@pytest.mark.parametrize(
    "field,value", [("day", "30"), ("month", "13"), ("year", "0"), ("day", "")]
)
def test_invalid_approval_date(field, value):
    original, notice, _ = pair("erratum")
    metadata(original).find("history/date/" + field).text = value
    with pytest.raises(ValidationError, match="history date"):
        validate_change_pair("erratum", original, notice)


@pytest.mark.parametrize("kind", TYPES)
def test_date_under_back_is_not_history(kind):
    original, notice, _ = pair(kind)
    history = metadata(original).find("history")
    metadata(original).remove(history)
    etree.SubElement(original, "back").append(history)
    with pytest.raises(ValidationError, match="history date"):
        validate_change_pair(kind, original, notice)


@pytest.mark.parametrize(
    "mutation", ["text", "plain_href", "nested", "duplicate_id", "missing_id"]
)
def test_relationship_structure(mutation):
    original, notice, _ = pair("addendum", translated=True)
    meta = metadata(original)
    relation = meta.find("related-article")
    if mutation == "text":
        relation.text = "10.1234/notice"
    elif mutation == "plain_href":
        relation.set("href", relation.attrib.pop(XLINK))
    elif mutation == "nested":
        meta.remove(relation)
        etree.SubElement(meta, "custom-meta-group").append(relation)
    elif mutation == "duplicate_id":
        original.find("sub-article/front-stub/related-article").set(
            "id", relation.get("id")
        )
    else:
        del relation.attrib["id"]
    with pytest.raises(ValidationError):
        validate_change_pair("addendum", original, notice)


@pytest.mark.parametrize("kind", TYPES)
def test_translation_relationship_required(kind):
    original, notice, _ = pair(kind, translated=True)
    stub = notice.find("sub-article/front-stub")
    stub.remove(stub.find("related-article"))
    with pytest.raises(ValidationError, match="relationship"):
        validate_change_pair(kind, original, notice)


@pytest.mark.parametrize("kind", ["addendum", "retraction", "partial-retraction"])
def test_notice_covers_original_languages(kind):
    original, notice, _ = pair(kind, translated=True)
    notice.remove(notice.find("sub-article"))
    with pytest.raises(ValidationError, match="languages"):
        validate_change_pair(kind, original, notice)


def test_single_language_erratum_is_allowed():
    original, notice, published = pair("erratum", translated=True)
    notice.remove(notice.find("sub-article"))
    assert validate_change_pair("erratum", original, notice, published) is None


@pytest.mark.parametrize("kind", TYPES)
def test_original_translation_cannot_be_removed(kind):
    original, notice, published = pair(kind, translated=True)
    original.remove(original.find("sub-article"))
    with pytest.raises(ValidationError, match="languages"):
        validate_change_pair(kind, original, notice, published)


@pytest.mark.parametrize("section", ["body/sec/p", "back/ref-list/ref/mixed-citation"])
def test_addendum_cannot_change_published_content(section):
    original, notice, published = pair("addendum")
    original.find(section).text = "A replacement."
    with pytest.raises(ValidationError, match="preserve"):
        validate_change_pair("addendum", original, notice, published)


def test_erratum_cannot_change_nested_text():
    original, notice, published = pair("erratum")
    original.find("body/sec/list/list-item/p").text = "Rewritten scientific content."
    with pytest.raises(ValidationError, match="rewrite"):
        validate_change_pair("erratum", original, notice, published)


def test_erratum_can_correct_citations_and_references():
    original, notice, published = pair("erratum")
    original.find("back/ref-list/ref/mixed-citation").text = "Corrected reference."
    paragraph = original.find("body/sec/p")
    etree.SubElement(paragraph, "xref", {"ref-type": "bibr", "rid": "ref1"}).text = "1"
    assert validate_change_pair("erratum", original, notice, published) is None


def test_erratum_doi_correction_uses_new_identity_not_notice_doi():
    original, notice, published = pair("erratum")
    metadata(original).find("article-id").text = "10.1234/corrected-original"
    metadata(notice).find("related-article").set(XLINK, "10.1234/corrected-original")
    assert validate_change_pair("erratum", original, notice, published) is None


def test_original_article_type_must_be_preserved():
    original, notice, published = pair("addendum")
    original.set("article-type", "review-article")
    with pytest.raises(ValidationError, match="article-type"):
        validate_change_pair("addendum", original, notice, published)


@pytest.mark.parametrize("kind", ["retraction", "partial-retraction"])
def test_retraction_cannot_leave_all_titles_unchanged(kind):
    original, notice, published = pair(kind, translated=True)
    for current, previous in zip(
        [original] + original.findall("sub-article"),
        [published] + published.findall("sub-article"),
    ):
        metadata(current).replace(
            metadata(current).find("title-group"),
            deepcopy(metadata(previous).find("title-group")),
        )
    with pytest.raises(ValidationError, match="titles"):
        validate_change_pair(kind, original, notice, published)
    # Without the published XML there is no baseline for this structural check.
    assert validate_change_pair(kind, original, notice) is None


@pytest.mark.parametrize("kind", ["retraction", "partial-retraction"])
@pytest.mark.parametrize("translated", [False, True])
@pytest.mark.parametrize(
    "title_path",
    [
        "title-group/article-title",
        "title-group/trans-title-group[@xml:lang='es']/trans-title",
    ],
)
@pytest.mark.parametrize("mutation", ["unchanged", "rewrite", "remove"])
def test_retraction_requires_addition_to_each_published_title(
    kind, translated, title_path, mutation
):
    original, notice, published = pair(kind, translated=True)
    current = original.find("sub-article") if translated else original
    previous = published.find("sub-article") if translated else published
    namespaces = {"xml": "http://www.w3.org/XML/1998/namespace"}
    title = metadata(current).find(title_path, namespaces)
    if mutation == "unchanged":
        title.text = metadata(previous).find(title_path, namespaces).text
    elif mutation == "rewrite":
        title.text = "An unrelated replacement — RETRACTED ARTICLE"
    else:
        title.getparent().remove(title)
    with pytest.raises(ValidationError, match="titles"):
        validate_change_pair(kind, original, notice, published)


@pytest.mark.parametrize("kind", ["retraction", "partial-retraction"])
def test_retraction_title_comparison_is_structural_and_language_based(kind):
    original, notice, published = pair(kind, translated=True)
    for current, previous in zip(
        [original] + original.findall("sub-article"),
        [published] + published.findall("sub-article"),
    ):
        group = metadata(current).find("title-group")
        old_group = metadata(previous).find("title-group")
        # No literal warning vocabulary is enforced: editorial QA checks wording.
        group.find("article-title").text = "Additional prefix: " + old_group.findtext(
            "article-title"
        )
        for translation in list(group.findall("trans-title-group")):
            language = translation.get(LANG)
            old_translation = next(
                node
                for node in old_group.findall("trans-title-group")
                if node.get(LANG) == language
            )
            translation.find("trans-title").text = (
                old_translation.findtext("trans-title") + " : additional suffix"
            )
            group.remove(translation)
            group.insert(1, translation)
    assert validate_change_pair(kind, original, notice, published) is None
    # Swapping language labels must not let unrelated titles substitute for each other.
    translations = metadata(original).findall("title-group/trans-title-group")
    translations[0].set(LANG, "es")
    translations[1].set(LANG, "fr")
    with pytest.raises(ValidationError, match="titles"):
        validate_change_pair(kind, original, notice, published)


def test_total_retraction_cannot_keep_back():
    original, notice, _ = pair("retraction")
    etree.SubElement(original, "back")
    with pytest.raises(ValidationError, match="back"):
        validate_change_pair("retraction", original, notice)


def test_total_retraction_cannot_keep_original_body():
    original, notice, published = pair("retraction")
    original.replace(original.find("body"), deepcopy(published.find("body")))
    with pytest.raises(ValidationError, match="published body"):
        validate_change_pair("retraction", original, notice, published)


def test_total_retraction_cannot_append_notice_to_old_body():
    original, notice, published = pair("retraction")
    original.find("body").append(deepcopy(published.find("body/sec")))
    with pytest.raises(ValidationError, match="published body"):
        validate_change_pair("retraction", original, notice, published)


@pytest.mark.parametrize("kind", TYPES)
def test_wrong_notice_type(kind):
    original, notice, _ = pair(kind)
    notice.set("article-type", "research-article")
    with pytest.raises(ValidationError, match="notice article-type"):
        validate_change_pair(kind, original, notice)


def test_partial_retraction_cannot_replace_everything():
    original, notice, published = pair("partial-retraction")
    original.find("body").clear()
    original.replace(original.find("body"), deepcopy(notice.find("body")))
    original.remove(original.find("back"))
    with pytest.raises(ValidationError, match="retain original"):
        validate_change_pair("partial-retraction", original, notice, published)


def test_partial_retraction_retains_nested_original_content():
    original, notice, published = pair("partial-retraction")
    original.find("body/sec").remove(original.find("body/sec/p"))
    assert (
        validate_change_pair("partial-retraction", original, notice, published) is None
    )


@pytest.mark.parametrize("kind", TYPES)
def test_main_and_translated_pdfs(kind):
    original, notice, _ = pair(kind, translated=True)
    files = [
        "original.xml",
        "original.pdf",
        "original-en.pdf",
        "notice.pdf",
        "notice-en.pdf",
    ]
    assert require_document_pdfs(original, files, "original.xml") is None
    assert require_document_pdfs(notice, files, "notice.xml") is None


@pytest.mark.parametrize(
    "files", [[], ["doc.pdf"], ["doc-en.pdf"], ["other/doc.pdf", "other/doc-en.pdf"]]
)
def test_missing_main_or_translation_pdf(files):
    root = article("10.1234/original")
    translate(root)
    with pytest.raises(ValidationError, match="Missing document PDF"):
        require_document_pdfs(root, files, "doc.xml")


def test_explicit_pdf_references_are_relative_and_override_fallback():
    root = article("10.1234/original")
    translation = translate(root)
    etree.SubElement(
        metadata(root), "self-uri", {"content-type": "pdf", XLINK: "pdf/main.pdf"}
    )
    etree.SubElement(
        metadata(translation),
        "self-uri",
        {"content-type": "pdf", XLINK: "pdf/english.pdf"},
    )
    files = ["issue/pdf/main.pdf", "issue/pdf/english.pdf"]
    assert require_document_pdfs(root, files, "issue/doc.xml") is None
    with pytest.raises(ValidationError, match="Missing document PDF"):
        require_document_pdfs(
            root, ["issue/doc.pdf", "issue/doc-en.pdf"], "issue/doc.xml"
        )


@pytest.mark.parametrize(
    "path",
    [
        "../doc.pdf",
        "/doc.pdf",
        "https://example.org/doc.pdf",
        "..%2Fdoc.pdf",
        "C:\\doc.pdf",
    ],
)
def test_unsafe_pdf_references(path):
    root = article("10.1234/original")
    etree.SubElement(metadata(root), "self-uri", {"content-type": "pdf", XLINK: path})
    with pytest.raises(ValidationError, match="Unsafe"):
        require_document_pdfs(root, ["doc.pdf"], "doc.xml")


def test_pdf_reference_requires_xlink_href():
    root = article("10.1234/original")
    etree.SubElement(
        metadata(root), "self-uri", {"content-type": "pdf", "href": "doc.pdf"}
    )
    with pytest.raises(ValidationError):
        require_document_pdfs(root, ["doc.pdf"], "doc.xml")


@pytest.mark.parametrize(
    "xml_filename,filenames",
    [
        ("../doc.xml", ["doc.pdf"]),
        ("doc.xml", ["../doc.pdf"]),
    ],
)
def test_package_paths_cannot_traverse(xml_filename, filenames):
    with pytest.raises(ValidationError, match="Unsafe"):
        require_document_pdfs(article("10.1234/original"), filenames, xml_filename)


@pytest.mark.parametrize("kind", ["erratum", "addendum"])
@pytest.mark.parametrize("original_type", [value[0] for value in TYPES.values()])
def test_corrective_articles_can_receive_further_changes(kind, original_type):
    original, notice, published = pair(kind)
    original.set("article-type", original_type)
    published.set("article-type", original_type)
    assert validate_change_pair(kind, original, notice, published) is None
    assert validate_change_pair(kind, original, notice) is None


@pytest.mark.parametrize(
    "doi", ["not-a-doi", "10.123/a", "10.1234567890/a", "10.1234/", "10.1234/a b"]
)
@pytest.mark.parametrize("side", [0, 1, 2])
def test_invalid_doi_is_rejected(doi, side):
    documents = pair("addendum")
    metadata(documents[side]).find("article-id").text = doi
    with pytest.raises(ValidationError, match="DOI"):
        validate_change_pair("addendum", *documents)


@pytest.mark.parametrize("translated", [False, True])
@pytest.mark.parametrize("field", ["title", "author"])
def test_addendum_preserves_bibliographic_metadata(translated, field):
    original, notice, published = pair("addendum", translated=translated)
    current = original.find("sub-article") if translated else original
    old = published.find("sub-article") if translated else published
    if field == "title":
        title = metadata(current).find("title-group")
        title[0].text = "A different title"
    else:
        for document in (current, old):
            group = etree.SubElement(metadata(document), "contrib-group")
            etree.SubElement(
                group, "contrib", {"contrib-type": "author"}
            ).text = "Original author"
        metadata(current).find("contrib-group/contrib").text = "Different author"
    with pytest.raises(ValidationError, match="preserve published metadata"):
        validate_change_pair("addendum", original, notice, published)


@pytest.mark.parametrize("field", ["relationship", "corrected-date", "received-date"])
@pytest.mark.parametrize("mutation", ["remove", "change"])
def test_addendum_preserves_previous_relationships_and_dates(field, mutation):
    original, notice, published = pair("addendum")
    if field == "relationship":
        previous = relate(published, "addendum", "10.1234/earlier-notice", "previous")
        current = deepcopy(previous)
        metadata(original).append(current)
    else:
        date_type = "corrected" if field == "corrected-date" else "received"
        previous_history = etree.SubElement(metadata(published), "history")
        previous = etree.SubElement(previous_history, "date", {"date-type": date_type})
        for name, value in (("day", "1"), ("month", "1"), ("year", "2020")):
            etree.SubElement(previous, name).text = value
        current = deepcopy(previous)
        metadata(original).find("history").insert(0, current)
    assert validate_change_pair("addendum", original, notice, published) is None
    if mutation == "remove":
        current.getparent().remove(current)
    elif field == "relationship":
        current.set(XLINK, "10.1234/changed")
    else:
        current.find("year").text = "2021"
    with pytest.raises(ValidationError, match="preserve published metadata"):
        validate_change_pair("addendum", original, notice, published)


@pytest.mark.parametrize("kind", ["addendum", "erratum"])
def test_pretty_print_and_attribute_order_do_not_change_content(kind):
    original, notice, published = pair(kind)
    for document in (original, published):
        paragraph = document.find("body/sec/p")
        paragraph.text = None
        etree.SubElement(
            paragraph, "italic", {"id": "i", "specific-use": "test"}
        ).text = "alpha"
        etree.SubElement(paragraph, "bold").text = "beta"
    original = etree.fromstring(etree.tostring(original, pretty_print=True))
    inline = original.find("body/sec/p/italic")
    attributes = list(inline.attrib.items())
    inline.attrib.clear()
    inline.attrib.update(reversed(attributes))
    assert validate_change_pair(kind, original, notice, published) is None


@pytest.mark.parametrize("kind", ["addendum", "erratum"])
def test_inline_word_spacing_is_not_ignored(kind):
    original, notice, published = pair(kind)
    for document in (original, published):
        paragraph = document.find("body/sec/p")
        paragraph.text = None
        etree.SubElement(paragraph, "italic").text = "alpha"
        etree.SubElement(paragraph, "bold").text = "beta"
    original.find("body/sec/p/italic").tail = " "
    with pytest.raises(ValidationError):
        validate_change_pair(kind, original, notice, published)


def test_partial_retraction_can_shorten_the_only_paragraph_without_unchanged_blocks():
    original, notice, published = pair("partial-retraction")
    for document in (original, published):
        document.find("body").clear()
        document.remove(document.find("back"))
    etree.SubElement(
        published.find("body"), "p"
    ).text = "Retained finding. Withdrawn finding."
    etree.SubElement(original.find("body"), "p").text = "Retained finding."
    assert (
        validate_change_pair("partial-retraction", original, notice, published) is None
    )


def test_partial_retraction_requires_nonempty_body():
    original, notice, published = pair("partial-retraction")
    original.find("body").clear()
    with pytest.raises(ValidationError, match="retain original"):
        validate_change_pair("partial-retraction", original, notice, published)


def test_total_retraction_matches_notice_in_corresponding_language():
    original, notice, published = pair("retraction", translated=True)
    original.find("sub-article/body/p").text = notice.find("body/p").text
    with pytest.raises(ValidationError, match="notice text"):
        validate_change_pair("retraction", original, notice, published)


def test_total_retraction_may_quote_a_published_paragraph_in_its_notice():
    original, notice, published = pair("retraction")
    quote = deepcopy(published.find("body/sec/p"))
    notice.find("body").append(quote)
    original.replace(original.find("body"), deepcopy(notice.find("body")))
    assert validate_change_pair("retraction", original, notice, published) is None


def test_total_retraction_compares_text_not_notice_markup_or_back():
    original, notice, published = pair("retraction")
    paragraph = notice.find("body/p")
    text = paragraph.text
    paragraph.text = None
    etree.SubElement(paragraph, "italic").text = text
    assert validate_change_pair("retraction", original, notice, published) is None


def test_total_retraction_cannot_use_unrelated_replacement_text():
    original, notice, published = pair("retraction")
    original.find("body/p").text = "Different explanation."
    with pytest.raises(ValidationError, match="notice text"):
        validate_change_pair("retraction", original, notice, published)


def test_pdf_fallback_respects_xml_directory():
    root = article("10.1234/original")
    assert require_document_pdfs(root, ["issue/doc.pdf"], "issue/doc.xml") is None
    with pytest.raises(ValidationError, match="Missing document PDF"):
        require_document_pdfs(root, ["other/doc.pdf"], "issue/doc.xml")
