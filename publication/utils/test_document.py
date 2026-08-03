from unittest import TestCase
from unittest.mock import MagicMock

from lxml import etree

from publication.utils.document import XMLArticle


def _create_xml_article(xml_string):
    xmltree = etree.fromstring(xml_string)
    xml_with_pre = MagicMock()
    xml_with_pre.xmltree = xmltree
    return XMLArticle(xml_with_pre)


class XMLArticleGetContribsTest(TestCase):
    def test_get_contribs_with_affiliation_missing_original_and_orgname(self):
        """Regression test: affiliations lacking both 'original' and 'orgname'
        should not raise TypeError in str.join()."""
        xml_string = """<article xmlns:xlink="http://www.w3.org/1999/xlink"
                article-type="research-article" xml:lang="es">
            <front>
                <article-meta>
                    <contrib-group>
                        <contrib contrib-type="author">
                            <name>
                                <surname>Silva</surname>
                                <given-names>Rafaela</given-names>
                            </name>
                            <xref ref-type="aff" rid="aff1"/>
                        </contrib>
                    </contrib-group>
                    <aff id="aff1">
                        <label>1</label>
                    </aff>
                </article-meta>
            </front>
        </article>"""

        article_xml = _create_xml_article(xml_string)
        result = article_xml.get_contribs()

        self.assertEqual(len(result["names"]), 1)
        self.assertEqual(result["names"][0]["surname"], "Silva")
        self.assertEqual(result["names"][0]["given_names"], "Rafaela")
        self.assertEqual(result["names"][0]["affiliation"], "")

    def test_get_contribs_with_valid_affiliation(self):
        xml_string = """<article xmlns:xlink="http://www.w3.org/1999/xlink"
                article-type="research-article" xml:lang="es">
            <front>
                <article-meta>
                    <contrib-group>
                        <contrib contrib-type="author">
                            <name>
                                <surname>Costa</surname>
                                <given-names>Ana</given-names>
                            </name>
                            <xref ref-type="aff" rid="aff1"/>
                        </contrib>
                    </contrib-group>
                    <aff id="aff1">
                        <institution content-type="original">Universidade de São Paulo, SP, Brasil</institution>
                    </aff>
                </article-meta>
            </front>
        </article>"""

        article_xml = _create_xml_article(xml_string)
        result = article_xml.get_contribs()

        self.assertEqual(len(result["names"]), 1)
        self.assertIn("Universidade de São Paulo", result["names"][0]["affiliation"])

    def test_get_contribs_with_no_affs(self):
        xml_string = """<article xmlns:xlink="http://www.w3.org/1999/xlink"
                article-type="research-article" xml:lang="es">
            <front>
                <article-meta>
                    <contrib-group>
                        <contrib contrib-type="author">
                            <name>
                                <surname>Pereira</surname>
                                <given-names>João</given-names>
                            </name>
                        </contrib>
                    </contrib-group>
                </article-meta>
            </front>
        </article>"""

        article_xml = _create_xml_article(xml_string)
        result = article_xml.get_contribs()

        self.assertEqual(len(result["names"]), 1)
        self.assertEqual(result["names"][0]["surname"], "Pereira")
        self.assertEqual(result["names"][0]["affiliation"], "")

    def test_get_contribs_with_no_contribs(self):
        xml_string = """<article xmlns:xlink="http://www.w3.org/1999/xlink"
                article-type="research-article" xml:lang="es">
            <front>
                <article-meta>
                </article-meta>
            </front>
        </article>"""

        article_xml = _create_xml_article(xml_string)
        result = article_xml.get_contribs()

        self.assertEqual(result["names"], [])
        self.assertEqual(result["collabs"], [])


class XMLArticleGetAbstractsTest(TestCase):
    def test_get_abstracts_with_p_tag(self):
        xml_string = """<article xml:lang="en">
            <front>
                <article-meta>
                    <abstract>
                        <title>Abstract</title>
                        <p>Simple abstract with a p tag.</p>
                    </abstract>
                    <trans-abstract xml:lang="pt">
                        <title>Resumo</title>
                        <p>Resumo simples com uma tag p.</p>
                    </trans-abstract>
                </article-meta>
            </front>
        </article>"""

        article_xml = _create_xml_article(xml_string)
        result = list(article_xml.get_abstracts())

        self.assertEqual(
            result,
            [
                {"language": "en", "text": "Simple abstract with a p tag."},
                {"language": "pt", "text": "Resumo simples com uma tag p."},
            ],
        )

    def test_get_abstracts_with_sections(self):
        xml_string = """<article xml:lang="en">
            <front>
                <article-meta>
                    <abstract>
                        <title>Abstract</title>
                        <sec><title>Objective:</title><p>obj text.</p></sec>
                        <sec><title>Method:</title><p>method text.</p></sec>
                    </abstract>
                </article-meta>
            </front>
        </article>"""

        article_xml = _create_xml_article(xml_string)
        result = list(article_xml.get_abstracts())

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["language"], "en")
        self.assertEqual(
            result[0]["text"], "Objective: obj text. Method: method text."
        )

    def test_get_abstracts_without_p_wrapper_regression_issue_1031(self):
        """Regression test for scieloorg/scms-upload#1031: legacy migrated
        XML (e.g. URY collection) may have abstract text sitting directly
        under <abstract>/<trans-abstract>, not wrapped in <p>. Extraction
        for this case lives in packtools (scieloorg/packtools#1272,
        released in 4.16.11); this test only confirms it comes through
        get_abstracts() transparently."""
        xml_string = """<article xml:lang="es">
            <front>
                <article-meta>
                    <abstract>
                        <title>Resumen:</title> Texto do resumo sem tag p.
                    </abstract>
                    <trans-abstract xml:lang="en">
                        <title>Abstract:</title> Abstract text without a p tag.
                    </trans-abstract>
                </article-meta>
            </front>
        </article>"""

        article_xml = _create_xml_article(xml_string)
        result = list(article_xml.get_abstracts())

        self.assertEqual(
            result,
            [
                {"language": "es", "text": "Texto do resumo sem tag p."},
                {"language": "en", "text": "Abstract text without a p tag."},
            ],
        )

    def test_get_abstracts_with_no_abstract(self):
        xml_string = """<article xml:lang="en">
            <front>
                <article-meta>
                </article-meta>
            </front>
        </article>"""

        article_xml = _create_xml_article(xml_string)
        result = list(article_xml.get_abstracts())

        self.assertEqual(result, [])
