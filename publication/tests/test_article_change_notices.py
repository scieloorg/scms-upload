"""XML -> public HTML and OPAC payload contracts (Packtools 4.18.1).

The panel selectors/placement come from the official 4.18.1 sources:
https://github.com/scieloorg/packtools/blob/4.18.1/packtools/catalogs/htmlgenerator/v3.0/article.xsl
https://github.com/scieloorg/packtools/blob/4.18.1/packtools/catalogs/htmlgenerator/v3.0/article-meta-related-article.xsl
https://github.com/scieloorg/packtools/blob/4.18.1/packtools/catalogs/htmlgenerator/v2.0/article-meta-related-article.xsl

These test the generated header notice, not merely a DOI somewhere in the body.
They do not test OPAC ingestion, browser/CSS appearance (including yellow), PDFs,
or OPAC's automatic reverse-link creation. Both XML directions are explicit.
Some SPS 1.10 types get the XSL's generic relationship heading rather than a
specific correction/retraction label; their precise semantics live in the payload.
"""

import json
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from lxml import etree
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from package.models import SPSPkg
from publication.api.document import ArticlePayload
from publication.utils.document import XMLArticle

XML_PATH = (
    Path(__file__).resolve().parents[2]
    / "pid_provider/fixtures/sub-article/2236-8906-hoehnea-49-e1082020.xml"
)
ORIGINAL_DOI = "10.1590/2236-8906-108/2020"

# Independent SPS 1.10 expectations: note article-type, note -> original,
# original -> note. Do not derive these from production choice tables.
CHANGE_TYPES = (
    ("correction", "corrected-article", "correction-forward"),
    ("addendum", "addended-article", "addendum"),
    ("retraction", "retracted-article", "retraction-forward"),
    ("partial-retraction", "retracted-article", "partial-retraction"),
)


def related_element(language, related_type, doi):
    return etree.fromstring(
        (
            '<related-article xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'id="related-{language}" ext-link-type="doi" '
            f'related-article-type="{related_type}" xlink:href="{doi}"/>'
        ).encode()
    )


def changed_document(source, article_type, doi, related_type, counterpart):
    """Copy the real contract fixture; alter metadata, not its original body."""
    tree = deepcopy(etree.parse(BytesIO(source)))
    root = tree.getroot()
    root.set("specific-use", "sps-1.10")
    root.set("article-type", article_type)
    meta = root.find("./front/article-meta")
    meta.find("article-id[@pub-id-type='doi']").text = doi
    meta.append(related_element("pt", related_type, counterpart))

    # This fixture has translated titles/tables but no fulltext translation.
    # Add a small translation using its real title and first body paragraph.
    translation = etree.fromstring(
        b'<sub-article id="translation-en" article-type="translation" '
        b'xml:lang="en"><front-stub/><body/></sub-article>'
    )
    stub = translation.find("front-stub")
    translated_doi = deepcopy(meta.find("article-id[@pub-id-type='doi']"))
    translated_doi.text = doi + ".en"
    stub.append(translated_doi)
    stub.append(deepcopy(meta.find("title-group")))
    stub.append(related_element("en", related_type, counterpart + ".en"))
    translation.find("body").append(deepcopy(root.find("./body//p")))
    root.append(translation)
    return tree


class ArticleChangeNoticeTests(unittest.TestCase):
    def setUp(self):
        self.source = XML_PATH.read_bytes()

    def render_pages(self, content):
        package = SPSPkg(
            sps_pkg_name="notice-contract", xml_uri="https://example.org/notice.xml"
        )
        # Never fetch the XML over HTTP; run the project's real HTML generator.
        with patch("package.models.fetch_data", return_value=content) as fetch:
            pages = list(package.generate_article_html_pages())
        fetch.assert_called_once_with(package.xml_uri)
        self.assertTrue(pages)
        for page in pages:
            self.assertNotIn("error", page, page)
            self.assertIn("<html", page["content"])
        self.assertEqual(len(pages), len({page["lang"] for page in pages}))
        return {page["lang"]: page["content"] for page in pages}

    def test_unmodified_real_fixture_has_no_change_notice(self):
        tree = etree.parse(BytesIO(self.source))
        article = XMLArticle(XMLWithPre("", tree))
        self.assertEqual(list(article.get_related_articles()), [])
        payload = {}
        ArticlePayload(payload)
        self.assertIsNone(json.loads(json.dumps(payload))["related_articles"])
        for content in self.render_pages(self.source).values():
            self.assertIn(ORIGINAL_DOI, content)
            self.assertEqual(
                etree.HTML(content).xpath(
                    "//div[contains(concat(' ', normalize-space(@class), ' '), ' article-correction-title ')]"
                ),
                [],
            )

    def test_reciprocal_notices_render_in_header_and_reach_opac_json(self):
        for note_type, note_relation, original_relation in CHANGE_TYPES:
            note_doi = ORIGINAL_DOI + "." + note_type
            for direction, article_type, doi, relation, counterpart in (
                ("note", note_type, note_doi, note_relation, ORIGINAL_DOI),
                (
                    "original",
                    "research-article",
                    ORIGINAL_DOI,
                    original_relation,
                    note_doi,
                ),
            ):
                with self.subTest(change=note_type, direction=direction):
                    tree = changed_document(
                        self.source, article_type, doi, relation, counterpart
                    )
                    article = XMLArticle(XMLWithPre("", tree))
                    self.assertEqual(article.main_article_type, article_type)
                    expected_xml = [
                        {
                            "ref_id": "related-pt",
                            "ext_link_type": "doi",
                            "related_type": relation,
                            "href": counterpart,
                        },
                        {
                            "ref_id": "related-en",
                            "ext_link_type": "doi",
                            "related_type": relation,
                            "href": counterpart + ".en",
                        },
                    ]
                    extracted = list(article.get_related_articles())
                    self.assertCountEqual(extracted, expected_xml)
                    payload = {}
                    builder = ArticlePayload(payload)
                    builder.add_document_type(article.main_article_type)
                    for item in extracted:
                        builder.add_related_article(**item)
                    opac = json.loads(json.dumps(payload))
                    self.assertEqual(opac["type"], article_type)
                    self.assertCountEqual(
                        opac["related_articles"],
                        [
                            {
                                "ref_id": "related-pt",
                                "related_type": relation,
                                "doi": counterpart,
                            },
                            {
                                "ref_id": "related-en",
                                "related_type": relation,
                                "doi": counterpart + ".en",
                            },
                        ],
                    )

                    pages = self.render_pages(etree.tostring(tree))
                    self.assertEqual(set(pages), {"pt", "en"})
                    for language, own_doi, target_doi in (
                        ("pt", doi, counterpart),
                        ("en", doi + ".en", counterpart + ".en"),
                    ):
                        with self.subTest(language=language):
                            content = pages[language]
                            self.assertIn(own_doi, content)
                            panels = etree.HTML(content).xpath(
                                "//div[contains(concat(' ', normalize-space(@class), ' '),"
                                " ' article-correction-title ')]"
                            )
                            self.assertEqual(len(panels), 1)
                            panel = panels[0]
                            ancestors = panel.xpath(
                                "ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' articleTxt ')][1]"
                            )
                            self.assertTrue(ancestors)
                            article_text = ancestors[0]
                            titles = article_text.xpath(
                                ".//h1[contains(concat(' ', normalize-space(@class), ' '), ' article-title ')]"
                            )
                            self.assertTrue(titles)
                            elements = list(article_text.iter())
                            self.assertLess(
                                elements.index(panel), elements.index(titles[0])
                            )
                            style = "".join(panel.get("style", "").lower().split())
                            self.assertNotIn("display:none", style)
                            self.assertNotIn("hidden", style)
                            headings = panel.xpath(
                                ".//div[contains(concat(' ', normalize-space(@class), ' '), ' panel-heading ')]"
                            )
                            self.assertTrue(headings)
                            heading = " ".join("".join(headings[0].itertext()).split())
                            self.assertTrue(heading.strip(" :"))
                            # Exact resolver URL, in the notice, not a body citation.
                            self.assertEqual(
                                panel.xpath(".//a/@href"),
                                ["https://doi.org/" + target_doi],
                            )
                    self.assertEqual(XML_PATH.read_bytes(), self.source)
