from django.test import SimpleTestCase
from lxml import etree

from htmlxml import analysis as an

P1 = "Os distúrbios osteomusculares relacionados ao trabalho podem gerar diferentes graus de incapacidade funcional"
P2_KEPT = "Tuomi et al"
P2_LOST = "propuseram um protocolo de avaliação, o índice de capacidade para o trabalho, resultado de pesquisas amplas na Finlândia"
P2_END = "consta a seguinte definição conceitual de Ilmarinen apresentada em curso ministrado no Brasil"
P3 = "Esse índice já foi aplicado em diferentes contextos na Finlândia e também no Brasil em diversos estudos"


def tree(text):
    return etree.fromstring(text)


def html_doc(body):
    return tree(f"<article><body>{body}</body></article>")


def xml_doc(body, front=""):
    return tree(
        '<article xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article">'
        f"<front>{front}</front><body>{body}</body>"
        '<back><ref-list><ref id="B15"><mixed-citation>R</mixed-citation></ref></ref-list></back></article>'
    )


FRONT_HTML = "<p><b>Autor Um; Autora Dois</b></p><p>Resumo: texto do resumo que vai para o front do XML.</p>"


class TextAnalysisTest(SimpleTestCase):
    def test_identical_text_has_no_findings(self):
        html = html_doc(f"{FRONT_HTML}<p>{P1}</p><p>{P3}</p>")
        xml = xml_doc(f"<sec><title>INTRODUÇÃO</title><p>{P1}</p><p>{P3}</p></sec>")
        result = an.text_analysis(html, xml)
        self.assertTrue(result["compared"])
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["percent"], 0)

    def test_lost_passage_after_citation_is_found_with_markup(self):
        html = html_doc(
            f"{FRONT_HTML}<p>{P1}</p>"
            f'<p>{P2_KEPT}<span style="sup">15</span> {P2_LOST}, elaborada por Fisher,'
            f'<a name="top11"/><a href="#back11"><span style="sup">*</span></a> {P2_END}.</p>'
            f"<p>{P3}</p>"
        )
        xml = xml_doc(
            f'<p>{P1}</p><p>{P2_KEPT}<sup><xref ref-type="bibr" rid="B15">15</xref></sup>'
            f"<sup>*</sup> {P2_END}.</p><p>{P3}</p>"
        )
        result = an.text_analysis(html, xml)
        self.assertGreater(result["percent"], 10)
        [found] = result["findings"]
        self.assertEqual(found["check"], "text_lost")
        self.assertEqual(found["key"], "span[sup] → a[href=#…]/span[sup] [after citation number]")
        self.assertIn("[[propuseram um protocolo", found["example"])
        self.assertIn("XML: ", found["example"])

    def test_front_matter_before_main_text_is_ignored(self):
        html = html_doc(f"<p>Título que não vai para o body do XML</p>{FRONT_HTML}<p>{P1}</p><p>{P3}</p>")
        xml = xml_doc(f"<p>{P1}</p><p>{P3}</p>")
        self.assertEqual(an.text_analysis(html, xml)["findings"], [])

    def test_symbol_font_is_not_a_loss(self):
        html = html_doc(f'<p>{P1}</p><p>{P3} pelo teste <font face="Symbol">c</font>2 com nível de significância.</p>')
        xml = xml_doc(f"<p>{P1}</p><p>{P3} pelo teste χ2 com nível de significância.</p>")
        self.assertEqual(an.text_analysis(html, xml)["findings"], [])

    def test_short_line_lost_is_minor(self):
        html = html_doc(f"<p>{P1}</p><p><b>Correspondência: fulano de tal</b></p><p>{P3}</p>")
        xml = xml_doc(f"<p>{P1}</p><p>{P3}</p>")
        [found] = an.text_analysis(html, xml)["findings"]
        self.assertEqual(found["check"], "short_text_lost")
        self.assertEqual(an.severity(found["check"]), an.SEVERITY_MINOR)

    def test_body_without_paragraphs_is_compared(self):
        html = html_doc(f"<div><span>{P1}</span><br/><span>{P2_LOST}</span><br/><span>{P3}</span></div>")
        xml = xml_doc(f"<p>{P1}</p><p>{P3}</p>")
        result = an.text_analysis(html, xml)
        self.assertTrue(result["compared"])
        self.assertEqual([f["check"] for f in result["findings"]], ["text_lost"])

    def test_not_compared_when_nothing_matches(self):
        html = html_doc(f"<p>{P2_LOST}</p>")
        xml = xml_doc(f"<p>{P1} {P3} {P1}</p>")
        result = an.text_analysis(html, xml)
        self.assertFalse(result["compared"])
        self.assertEqual(result["findings"][0]["check"], "text_not_compared")


class SeverityTest(SimpleTestCase):
    def test_every_check_has_severity_and_texts(self):
        for check in an.CHECKS:
            self.assertIn(check, an.SEVERITY, check)
            for lang in ("en", "pt", "es"):
                an.t(f"check_{check}", lang)
                an.t(f"desc_{check}", lang)
        for severity in an.SEVERITIES:
            an.t(f"severity_{severity}", "pt")
            an.t(f"severity_desc_{severity}", "es")
        for entry in an.TEXTS.values():
            self.assertEqual(set(entry), {"en", "pt", "es"})

    def test_attention_points_are_critical_and_major_only(self):
        findings = [
            an.finding("text_lost"),
            an.finding("non_jats_element", "font"),
            an.finding("html_not_converted", "a[name=topN]"),
            an.finding("no_html_text"),
        ]
        self.assertEqual(an.attention_points(findings), 2)
        self.assertEqual(an.max_severity(findings), an.SEVERITY_CRITICAL)
        self.assertEqual(an.max_severity([]), "")

    def test_figures_and_tables_alone_are_not_attention_points(self):
        xml = xml_doc(
            f'<p>{P1}</p><fig id="f1"><graphic xlink:href="f1.jpg"/></fig>'
            f'<table-wrap id="t1"><graphic xlink:href="t1.jpg"/></table-wrap><p>{P3}</p>'
        )
        html = html_doc(f'<p>{P1}</p><img src="/img/revistas/rsp/f1.jpg"/><p>{P3}</p>')
        data = {
            "article_type": "research-article", "n_references": 1,
            "xml_ref_mixed_citation_total": 1, "xml_ref_elem_citation_total": 1,
            "xml_text_lang_total": 1, "html_img_total": 1, "xml_graphic_total": 2,
            "xml_fig_total": 1, "xml_table_wrap_total": 1,
        }
        evaluation = an.evaluate(html, xml, data, "rsp")
        self.assertEqual(an.attention_points(evaluation["findings"]), 0, evaluation["findings"])


FRONT_XML = (
    "<article-meta><title-group><article-title>Tratamiento médico en pacientes con infestación "
    "por Angiostrongylus costaricensis</article-title></title-group>"
    "<contrib-group><contrib><name><surname>Huertas-Franco</surname><given-names>Verny</given-names></name></contrib>"
    "<contrib><name><surname>Camacho-Fernández</surname><given-names>Álvaro</given-names></name></contrib></contrib-group>"
    f"<abstract><title>Resumen</title><p>{P1}</p></abstract>"
    f'<trans-abstract xml:lang="en"><title>Abstract</title><p>{P3}</p></trans-abstract>'
    "</article-meta>"
)


class FrontInBodyTest(SimpleTestCase):
    def test_front_repeated_at_the_start_of_the_body(self):
        xml = xml_doc(
            '<p align="center">Tratamiento médico en pacientes con infestación por '
            "<italic>Angiostrongylus costaricensis</italic></p>"
            "<p>Verny Huertas- Franco, Álvaro Camacho- Fernández.</p>"
            f"<p>Resumen</p><p>{P1}</p><sec><title>Caso clínico</title><p>{P2_END}</p></sec>",
            front=FRONT_XML,
        )
        findings = an.front_in_body_findings(xml)
        self.assertEqual(
            {f["key"] for f in findings}, {"article-title", "contrib-group", "abstract"}
        )
        self.assertEqual({f["check"] for f in findings}, {"front_in_body"})
        self.assertEqual(an.severity("front_in_body"), an.SEVERITY_MAJOR)

    def test_body_without_front(self):
        xml = xml_doc(f"<sec><title>Introducción</title><p>{P2_END}</p></sec>", front=FRONT_XML)
        self.assertEqual(an.front_in_body_findings(xml), [])

    def test_sub_article_front_stub(self):
        xml = tree(
            "<article><front><article-meta/></front><body><p>x</p></body>"
            f'<sub-article article-type="translation"><front-stub><abstract><p>{P3}</p></abstract></front-stub>'
            f"<body><p>{P3}</p><p>{P1}</p></body></sub-article></article>"
        )
        self.assertEqual([f["key"] for f in an.front_in_body_findings(xml)], ["abstract"])

    def test_signature_at_the_end_of_an_editorial_is_not_front(self):
        xml = xml_doc(
            f"<p>{P2_END}</p><p>{P2_LOST}</p><p>{P2_END}</p><p>{P2_LOST}</p>"
            "<p>Verny Huertas-Franco, Álvaro Camacho-Fernández</p>",
            front=FRONT_XML,
        )
        self.assertEqual(an.front_in_body_findings(xml), [])
