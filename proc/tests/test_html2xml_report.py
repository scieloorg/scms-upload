import csv
import io
import tempfile
import zipfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from lxml import etree

from collection.models import Collection
from htmlxml.models import HTMLXML
from migration.models import MigratedArticle
from proc import html2xml_report as hr
from proc import problem_report as pr
from proc.models import ArticleProc, ArticleProcResult, IssueProc, JournalProc, ProblemReport
from tracker import choices as tracker_choices

User = get_user_model()
DONE = tracker_choices.PROGRESS_STATUS_DONE
BLOCKED = tracker_choices.PROGRESS_STATUS_BLOCKED

LIB = "/usr/local/lib/python3.11/site-packages/scielo_classic_website/spsxml"


def step_exception(number, func, message="error parsing attribute name, line 1, column 222"):
    return {
        "type": "<class 'lxml.etree.XMLSyntaxError'>",
        "action": f"Convert HTML to XML - step {number} failed {func}",
        "detail": None,
        "message": (
            "Traceback (most recent call last):\n"
            f'  File "{LIB}/sps_xml_body_pipes.py", line 136, in convert_html_to_xml\n'
            "    document.xml_body_and_back.append(call_(document))\n"
            '  File "/usr/local/lib/python3.11/site-packages/plumber.py", line 109, in decorated\n'
            "    return f(*args)\n"
            f'  File "{LIB}/sps_xml_body_pipes.py", line 483, in transform\n'
            "    xml = ET.fromstring(raw.xml_body_and_back[-1])\n"
            '  File "src/lxml/etree.pyx", line 3257, in lxml.etree.fromstring\n'
            f"lxml.etree.XMLSyntaxError: {message}\n"
        ),
    }


def tree(text):
    return etree.fromstring(text)


XML_OK = """<article xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:mml="http://www.w3.org/1998/Math/MathML" article-type="research-article">
<body><p>Texto <xref ref-type="bibr" rid="B1">1</xref> <mml:math><mml:mi>x</mml:mi></mml:math></p>
<fig id="f1"><graphic xlink:href="f1.jpg"/></fig></body>
<back><ref-list><ref id="B1"><mixed-citation>R</mixed-citation></ref></ref-list></back>
</article>"""

XML_BAD = """<article xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article">
<body><p>Texto <xref ref-type="bibr" rid="1">1</xref> <font face="Symbol">a</font></p>
<p><xref ref-type="number" rid="B1">1</xref><element id="autor1"/></p>
<table-wrap id="t1"/><fig id="f1"><label>Fig</label></fig><fig id="f1"><graphic xlink:href="x.jpg"/></fig>
</body>
<back><ref-list><ref id="B1"><mixed-citation>R</mixed-citation></ref></ref-list></back>
</article>"""

HTML = """<article><body>
<p><a href="#B1">1</a> <a href="#nao-existe">2</a> <a name="t1"/></p>
</body></article>"""

HTML_OK = """<article><body><p><a href="#B1">1</a></p></body></article>"""


class FailureFindingsTest(TestCase):
    def test_first_failed_step_is_the_cause_and_cascade_is_one_finding(self):
        detail = {
            "exceptions": [
                step_exception(4, "convert_html_to_xml_step_40_basic_html_to_xml"),
                step_exception(3, "convert_html_to_xml_step_30_embed_html"),
                step_exception(5, "convert_html_to_xml_step_50_break_to_p"),
            ]
        }
        found = hr.failure_findings(DONE, detail)
        checks = [f["check"] for f in found]
        self.assertEqual(checks, ["step_failure", "step_failure_after"])
        self.assertEqual(
            found[0]["key"],
            "convert_html_to_xml_step_30_embed_html | lxml.etree.XMLSyntaxError | "
            "sps_xml_body_pipes.py:transform | error parsing attribute name, line <N>, column <N>",
        )
        self.assertEqual(found[1]["count"], 2)
        self.assertIn("same error as convert_html_to_xml_step_30_embed_html", found[1]["key"])

    def test_later_step_with_another_error_is_its_own_category(self):
        detail = {
            "exceptions": [
                step_exception(3, "convert_html_to_xml_step_30_embed_html"),
                step_exception(8, "convert_html_to_xml_step_80_fix_sec", "other problem"),
            ]
        }
        found = hr.failure_findings(DONE, detail)
        self.assertEqual([f["check"] for f in found], ["step_failure", "step_failure_after"])
        self.assertTrue(found[1]["key"].startswith("convert_html_to_xml_step_80_fix_sec"))

    def test_same_message_in_different_articles_same_key(self):
        a = hr.failure_findings(DONE, {"exceptions": [step_exception(3, "s30", "tag x line 10")]})
        b = hr.failure_findings(DONE, {"exceptions": [step_exception(3, "s30", "tag x line 99")]})
        self.assertEqual(a[0]["key"], b[0]["key"])

    def test_blocked_report_zip_and_other_exceptions(self):
        detail = {
            "exceptions": [{
                "action": "Processing citation 12",
                "type": "KeyError",
                "message": "Traceback (most recent call last):\n  File \"/x/sps_xml_refs.py\", line 1, in transform\nKeyError: 'v30'\n",
            }],
            "exception_type": "<class 'str'>",
            "exception_message": "Traceback (most recent call last):\n  File \"/x/htmlxml/models.py\", line 1, in html_to_xml\nValueError: boom\n",
            "report_exceptions": "Error generating HTML to XML report: x Traceback (most recent call last):\nAttributeError: y\n",
            "zip_exceptions": ["Failed to write step_001.xml to zip: z"],
        }
        found = {f["check"]: f for f in hr.failure_findings(DONE, detail)}
        self.assertEqual(found["conversion_exception"]["key"], "Processing citation <N> | KeyError | sps_xml_refs.py:transform | '<V>'")
        self.assertEqual(found["conversion_blocked"]["key"], "ValueError | models.py:html_to_xml | boom")
        self.assertIn("AttributeError", found["report_error"]["key"])
        self.assertIn("step_<N>.xml", found["zip_error"]["key"])

    def test_no_event(self):
        self.assertEqual(hr.failure_findings(BLOCKED, None, has_event=False)[0]["check"], "no_event")
        self.assertEqual(hr.failure_findings(DONE, None, has_event=False), [])

    def test_code_location_prefers_converter_library(self):
        tb = step_exception(3, "s")["message"]
        self.assertEqual(hr.code_location(tb), "sps_xml_body_pipes.py:transform")
        self.assertEqual(hr.code_location('File "/a/b.py", line 1, in f\n'), "b.py:f")


class ContentFindingsTest(TestCase):
    def checks(self, **data):
        base = {"article_type": "research-article", "xml_text_lang_total": 1}
        base.update(data)
        return {f["check"]: f for f in hr.content_findings(base)}

    def test_empty_body(self):
        self.assertIn("body_lost", self.checks(empty_body=True, n_paragraphs=10))
        self.assertIn("no_html_text", self.checks(empty_body=True, n_paragraphs=0))

    def test_references(self):
        self.assertIn("refs_missing", self.checks(n_references=5))
        found = self.checks(n_references=5, xml_ref_mixed_citation_total=3, xml_ref_elem_citation_total=3)
        self.assertEqual(found["refs_count_differs"]["key"], "fewer in XML")
        self.assertNotIn("refs_elem_vs_mixed", found)
        found = self.checks(n_references=3, xml_ref_mixed_citation_total=3, xml_ref_elem_citation_total=2)
        self.assertEqual(found["refs_elem_vs_mixed"]["count"], 1)

    def test_translation_article_type_images_tables(self):
        found = self.checks(
            html_translation_langs="en-es", xml_text_lang_total=2, article_type="tr",
            html_img_total=3, xml_graphic_total=1, xml_inline_graphic_total=1,
            html_table_total=2, xml_table_wrap_total=0,
        )
        self.assertEqual(found["translation_missing"]["count"], 1)
        self.assertEqual(found["article_type_not_jats"]["key"], "tr")
        self.assertEqual(found["images_fewer_in_xml"]["count"], 1)
        self.assertEqual(found["tables_fewer_in_xml"]["count"], 2)

    def test_clean_article(self):
        self.assertEqual(self.checks(), {})


class StructureAndHtmlFindingsTest(TestCase):
    def test_clean_xml_has_no_findings(self):
        self.assertEqual(hr.structure_findings(tree(XML_OK)), [])

    def test_defects(self):
        found = {(f["check"], f["key"]): f for f in hr.structure_findings(tree(XML_BAD))}
        self.assertIn(("non_jats_element", "font"), found)
        self.assertIn(("non_jats_element", "element"), found)
        self.assertIn(("xref_broken_rid", "bibr"), found)
        self.assertIn(("xref_ref_type_invalid", "number"), found)
        self.assertIn(("duplicate_id", "fig"), found)
        self.assertIn(("table_wrap_empty", ""), found)
        self.assertIn(("fig_empty", ""), found)
        # exemplo sem a declaração de namespace
        self.assertEqual(found[("non_jats_element", "font")]["example"], '<font face="Symbol">a</font>')

    def test_html_not_converted(self):
        found = {(f["check"], f["key"]): f for f in hr.html_findings(tree(HTML), tree(XML_OK), "rsp")}
        self.assertEqual(found[("html_not_converted", "a[href=#…]")]["count"], 1)
        self.assertIn('href="#nao-existe"', found[("html_not_converted", "a[href=#…]")]["example"])
        self.assertIn(("html_not_converted", "a[name=tN]"), found)

    def test_patterns(self):
        self.assertEqual(hr.a_href_pattern("mailto:a@b", "", "rsp"), "a[href=mailto]")
        self.assertEqual(hr.a_href_pattern("/img/revistas/rsp/a.gif", "", "rsp"), "a[href=image]")
        self.assertEqual(hr.a_href_pattern("http://x.org", "", "rsp"), "a[href=url]")
        self.assertEqual(hr.a_href_pattern("a01.pdf", "", "rsp"), "a[href=*.pdf]")
        self.assertEqual(hr.src_pattern("img", "/img/revistas/rsp/x.gif", "rsp"), "img[src=journal-dir]")
        self.assertEqual(hr.a_name_pattern("Back12"), "a[name=backN]")
        self.assertEqual(hr.a_name_pattern("top"), "a[name=word]")


class TextsTest(TestCase):
    def test_all_texts_have_three_languages(self):
        for key, entry in hr.TEXTS.items():
            self.assertEqual(set(entry), {"en", "pt", "es"}, key)

    def test_every_check_group_nature_and_spread_has_labels(self):
        for check, (group, nature) in hr.CHECKS.items():
            for lang in pr.LANGUAGES:
                hr.t(f"check_{check}", lang)
                hr.t(f"desc_{check}", lang)
                hr.t(f"group_{group}", lang)
                hr.t(f"nature_{nature}", lang)
        for spread in ("single", "concentrated", "spread"):
            hr.t(f"spread_{spread}", "pt")
        for kind in hr.FILE_KINDS:
            hr.t(f"sheet_{kind}", "es")


class Html2xmlReportGenerationTest(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(acron="scl", name="SciELO Brasil", user=self.user)
        self.rsp = self._issue("rsp", "0034-8910", "v38n2")
        self.bjmbr = self._issue("bjmbr", "0100-879X", "v37n1")
        self.a1 = self._article(self.rsp, "S0034-89102004000200001", XML_BAD)
        self.a2 = self._article(self.bjmbr, "S0100-879X2004000100001", XML_BAD)
        self.ok = self._article(self.rsp, "S0034-89102004000200002", XML_OK, html=HTML_OK)
        self.blocked = self._article(
            self.rsp, "S0034-89102004000200003", None, status=BLOCKED,
            detail={"exceptions": [
                step_exception(3, "convert_html_to_xml_step_30_embed_html"),
                step_exception(4, "convert_html_to_xml_step_40_basic_html_to_xml"),
            ]},
            completed=False,
        )

    def tearDown(self):
        self.override.disable()
        self.media.cleanup()

    def _issue(self, acron, issn, folder):
        journal_proc = JournalProc.objects.create(
            collection=self.collection, pid=issn, acron=acron, creator=self.user,
        )
        return IssueProc.objects.create(
            collection=self.collection, journal_proc=journal_proc,
            pid=issn + "20040002", issue_folder=folder, creator=self.user,
        )

    def _article(self, issue_proc, pid, xml, status=DONE, detail=None, completed=True, html=HTML):
        migrated = MigratedArticle.objects.create(collection=self.collection, pid=pid, creator=self.user)
        htmlxml = HTMLXML.objects.create(
            migrated_article=migrated, creator=self.user, html2xml_status=status,
            article_type="research-article", n_references=1,
            xml_ref_mixed_citation_total=1, xml_ref_elem_citation_total=1, xml_text_lang_total=1,
        )
        if xml:
            htmlxml.file.name = default_storage.save(f"t/{pid}/{pid}.xml", ContentFile(xml.encode("utf-8")))
            htmlxml.bb_init_file.name = default_storage.save(f"t/{pid}/initial_html.xml", ContentFile(html.encode("utf-8")))
            htmlxml.save()
        proc = ArticleProc.objects.create(
            collection=self.collection, issue_proc=issue_proc, pid=pid, pkg_name=pid[-5:],
            migrated_data=migrated, creator=self.user,
        )
        op = ArticleProcResult.create(self.user, proc, "html_to_xml")
        op.finish(self.user, completed=completed, detail=detail or {"exceptions": [], "xml_created": True})
        return proc

    def _csv(self, report, kind):
        with report.file.open("rb") as f:
            zf = zipfile.ZipFile(io.BytesIO(f.read()))
        number = hr.FILE_KINDS.index(kind) + 1
        name = next(n for n in zf.namelist() if n.startswith(f"{number}-"))
        text = zf.read(name).decode("utf-8-sig")
        if kind == "readme":
            return list(csv.reader(io.StringIO(text)))
        return list(csv.DictReader(io.StringIO(text)))

    def test_categories_spread_and_files(self):
        report = ProblemReport.generate(
            {"collection_acron_list": ["scl"]}, ["article"], user=self.user,
            language="en", report_type=ProblemReport.REPORT_HTML2XML,
        )
        self.assertEqual(report.status, ProblemReport.STATUS_DONE)
        self.assertEqual(report.item_types, "article")
        self.assertIn("[html2xml]", report.scope_label)
        self.assertIn("-html2xml-", report.file.name)
        self.assertEqual(report.stats["coverage"]["article"], {"total": 4, "processed": 4})
        # o artigo sem achados conta como analisado, mas não como "com achados"
        self.assertEqual(report.stats["total_analyzed"], 4)
        self.assertEqual(report.total_items, 3)

        summary = {(r["Check (code)"], r["Detail (pattern)"]): r for r in self._csv(report, "summary")}
        font = summary[("non_jats_element", "font")]
        self.assertEqual(font["Articles"], "2")
        self.assertEqual(font["Journals"], "2")
        self.assertEqual(font["Spread"], "spread (likely systematic)")
        self.assertEqual(font["Probable nature"], "converter bug")
        step = next(r for k, r in summary.items() if k[0] == "step_failure")
        self.assertEqual(step["Spread"], "1 journal (likely data)")
        self.assertIn("convert_html_to_xml_step_30_embed_html", step["Detail (pattern)"])
        self.assertIn(("step_failure_after", next(k[1] for k in summary if k[0] == "step_failure_after")), summary)

        findings = self._csv(report, "findings")
        self.assertTrue(all(
            "/admin/snippets/htmlxml/htmlxml/edit/" in r["Link (conversion: steps ZIP and report)"]
            for r in findings
        ))
        self.assertNotIn("S0034-89102004000200002", {r["PID"] for r in findings})
        articles = self._csv(report, "articles")
        self.assertEqual(len(articles), 4)
        journals = {r["Journal"]: r for r in self._csv(report, "journals")}
        self.assertEqual(journals["rsp"]["Analyzed articles"], "3")
        self.assertEqual(journals["rsp"]["Articles with findings"], "2")
        status = {(r["Conversion status"], r["Total"]) for r in self._csv(report, "status")}
        self.assertIn((DONE, "3"), status)
        self.assertEqual(len(self._csv(report, "checks")), len(hr.CHECKS))

    def test_does_not_replace_problem_report_of_same_scope(self):
        scope = {"collection_acron_list": ["scl"]}
        problems = ProblemReport.generate(scope, ["article"], user=self.user, language="en")
        ProblemReport.generate(scope, ["article"], user=self.user, language="en", report_type="html2xml")
        self.assertTrue(ProblemReport.objects.filter(pk=problems.pk).exists())
        self.assertTrue(problems.file.name.split("/")[-1].count("-problems-"))

    def test_scope_and_max_items(self):
        report = ProblemReport.generate(
            {"journal_acron_list": ["bjmbr"]}, ["article"], user=self.user, report_type="html2xml"
        )
        self.assertEqual(report.stats["coverage"]["article"]["total"], 1)
        report = ProblemReport.generate(
            {}, ["article"], user=self.user, report_type="html2xml", max_items=2
        )
        self.assertEqual(report.status, ProblemReport.STATUS_PARTIAL)
        self.assertEqual(report.stats["coverage"]["article"], {"total": 4, "processed": 2})

    def test_unreadable_xml_does_not_stop_the_report(self):
        htmlxml = HTMLXML.objects.get(migrated_article=self.ok.migrated_data)
        htmlxml.file.name = default_storage.save("t/broken.xml", ContentFile(b"<article><p></article>"))
        htmlxml.save()
        report = ProblemReport.generate({}, ["article"], user=self.user, report_type="html2xml", language="en")
        self.assertEqual(report.status, ProblemReport.STATUS_DONE)
        checks = {r["Check (code)"] for r in self._csv(report, "summary")}
        self.assertIn("xml_unreadable", checks)

    def test_management_command(self):
        out = io.StringIO()
        call_command("generate_problem_report", "--report-type", "html2xml", "--collection", "scl", stdout=out)
        self.assertIn("non_jats_element", out.getvalue())


class OnDemandHtml2xmlReportTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin", email="a@example.com", password="x")
        Collection.get_or_create(acron="scl", name="SciELO Brasil", user=self.admin)
        self.client.force_login(self.admin)

    @patch("proc.tasks.task_generate_problem_report.delay")
    def test_post_schedules_html2xml_report(self, mock_delay):
        response = self.client.post(
            reverse("proc:generate_problem_report"),
            {
                "report_type": "html2xml",
                "content_type": "articles",
                "collection_acron_list": ["scl"],
                "updated_from": "2026-11-01",
                "max_items": "300",
            },
        )
        self.assertEqual(response.status_code, 302)
        kwargs = mock_delay.call_args.kwargs
        self.assertEqual(kwargs["report_type"], "html2xml")
        report = ProblemReport.objects.get(pk=kwargs["problem_report_id"])
        self.assertEqual(report.report_type, ProblemReport.REPORT_HTML2XML)
        self.assertEqual(report.item_types, "article")

    def test_task_uses_report_type_when_it_creates_the_record(self):
        from proc.tasks import task_generate_problem_report

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            result = task_generate_problem_report(
                username="admin", report_type="html2xml", collection_acron_list=["scl"]
            )
        report = ProblemReport.objects.get(pk=result["problem_report_id"])
        self.assertEqual(report.report_type, "html2xml")
        self.assertEqual(report.status, ProblemReport.STATUS_DONE)
