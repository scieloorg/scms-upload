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
