import io
import tempfile
import zipfile
from unittest.mock import Mock, PropertyMock, patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from collection.models import Collection
from htmlxml import review
from htmlxml.exceptions import Html2xmlBlockingIssuesError
from htmlxml.models import HTMLXML, Html2xmlIssue, Html2xmlIssueCategory, Html2xmlProblem
from migration.models import MigratedArticle
from proc.models import ArticleProc, ArticleProcResult, IssueProc, JournalProc

User = get_user_model()

P1 = "Os distúrbios osteomusculares relacionados ao trabalho podem gerar diferentes graus de incapacidade funcional"
LOST = "propuseram um protocolo de avaliação, o índice de capacidade para o trabalho, resultado de pesquisas amplas na Finlândia"
P3 = "Esse índice já foi aplicado em diferentes contextos na Finlândia e também no Brasil em diversos estudos"

XML = (
    '<article xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article">'
    f"<body><p>{P1}</p><p>Tuomi et al<sup>15</sup> consta a definição.</p><p>{P3}</p></body>"
    '<back><ref-list><ref id="B1"><mixed-citation>R</mixed-citation><element-citation/></ref></ref-list></back></article>'
)
XML_BAD = XML.replace("<body>", "<body><font>x</font>")
HTML_CLEAN = f"<article><body><p>{P1}</p><p>Tuomi et al<span style=\"sup\">15</span> consta a definição.</p><p>{P3}</p></body></article>"
HTML_LOSS = (
    f"<article><body><p>{P1}</p><p>Tuomi et al<span style=\"sup\">15</span> {LOST}, "
    f"consta a definição.</p><p>{P3}</p></body></article>"
)


class ReviewTestMixin:
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(acron="scl", name="SciELO Brasil", user=self.user)
        journal_proc = JournalProc.objects.create(
            collection=self.collection, pid="0034-8910", acron="rsp", creator=self.user
        )
        self.issue_proc = IssueProc.objects.create(
            collection=self.collection, journal_proc=journal_proc, pid="0034-891020040002",
            issue_folder="v38n2", creator=self.user,
        )

    def tearDown(self):
        self.override.disable()
        self.media.cleanup()

    def _conversion(self, pid, xml=XML, html=HTML_CLEAN, status="DONE", detail=None, html_in_zip=False,
                    collection=None):
        collection = collection or self.collection
        migrated = MigratedArticle.objects.create(collection=collection, pid=pid, creator=self.user)
        htmlxml = HTMLXML.objects.create(
            migrated_article=migrated, creator=self.user, html2xml_status=status,
            n_references=1, attention_demands=7, quality="NOT_EVALUATED",
        )
        if xml:
            htmlxml.file.name = default_storage.save(f"t/{pid}/a.xml", ContentFile(xml.encode()))
        if html_in_zip:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as zf:
                zf.writestr("step_001.xml", "<x/>")
                zf.writestr("step_002.xml", html)
            htmlxml.conversion_steps_zip_file.name = default_storage.save(f"t/{pid}/a.zip", ContentFile(buffer.getvalue()))
        elif html:
            htmlxml.bb_init_file.name = default_storage.save(f"t/{pid}/initial_html.xml", ContentFile(html.encode()))
        htmlxml.save()
        proc = ArticleProc.objects.create(
            collection=collection, issue_proc=self.issue_proc, pid=pid,
            migrated_data=migrated, creator=self.user,
        )
        op = ArticleProcResult.create(self.user, proc, "html_to_xml")
        op.finish(self.user, completed=status != "BLOCKED", detail=detail or {"exceptions": []})
        return htmlxml, proc


class ReviewConversionTest(ReviewTestMixin, TestCase):
    def test_clean_conversion(self):
        htmlxml, proc = self._conversion("S0034-89102004000200001")
        result = review.review_existing(htmlxml)
        self.assertEqual(result["severity"], "ok")
        self.assertEqual(result["issues"], 0)
        htmlxml.refresh_from_db()
        self.assertEqual(htmlxml.review_severity, "ok")
        self.assertEqual(htmlxml.review_text_lost, 0)
        self.assertIsNotNone(htmlxml.reviewed_at)
        # a abordagem antiga não é alterada
        self.assertEqual((htmlxml.attention_demands, htmlxml.quality), (7, "NOT_EVALUATED"))

    def test_problems_are_grouped_in_shared_categories(self):
        a, _ = self._conversion("S0034-89102004000200001", xml=XML_BAD, html=HTML_LOSS)
        b, _ = self._conversion("S0034-89102004000200002", xml=XML_BAD, html=HTML_LOSS)
        review.review_existing(a)
        result = review.review_existing(b)
        self.assertEqual(result["severity"], "critical")
        checks = set(Html2xmlIssueCategory.objects.values_list("check_code", flat=True))
        self.assertEqual(checks, {"text_lost", "non_jats_element"})
        text_lost = Html2xmlIssueCategory.objects.get(check_code="text_lost")
        self.assertEqual(text_lost.key, "span[sup] → text [after citation number]")
        problem = Html2xmlProblem.objects.get(category=text_lost)
        self.assertEqual(problem.collection, self.collection)
        self.assertEqual(problem.issues.count(), 2)
        issue = problem.issues.get(htmlxml=a)
        self.assertEqual((issue.collection_acron, issue.journal_acron, issue.issue_folder), ("scl", "rsp", "v38n2"))
        self.assertIn("<mark>propuseram um protocolo", issue.example_html())
        a.refresh_from_db()
        self.assertGreater(a.review_text_lost, 10)

    def test_review_again_replaces_occurrences_and_keeps_triage(self):
        htmlxml, _ = self._conversion("S0034-89102004000200001", xml=XML_BAD)
        review.review_existing(htmlxml)
        problem = Html2xmlProblem.objects.get()
        problem.status = Html2xmlProblem.STATUS_CONVERTER
        problem.note = "reportado"
        problem.save()
        review.review_existing(htmlxml)
        self.assertEqual(Html2xmlIssue.objects.count(), 1)
        problem.refresh_from_db()
        self.assertEqual((problem.status, problem.note), ("converter", "reportado"))

    def test_failed_conversion_is_reviewed_from_the_event(self):
        detail = {
            "exceptions": [],
            "exception_message": 'Traceback (most recent call last):\n  File "/x/models.py", line 1, in f\nValueError: boom\n',
        }
        htmlxml, _ = self._conversion("S0034-89102004000200001", xml=None, html=None, status="BLOCKED", detail=detail)
        result = review.review_existing(htmlxml)
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(Html2xmlIssueCategory.objects.get().check_code, "conversion_blocked")

    def test_initial_html_from_steps_zip_when_missing(self):
        htmlxml, _ = self._conversion("S0034-89102004000200001", html=HTML_LOSS, html_in_zip=True)
        review.review_existing(htmlxml)
        self.assertEqual(
            set(Html2xmlIssueCategory.objects.values_list("check_code", flat=True)), {"text_lost"}
        )

    def test_review_error_does_not_interrupt_conversion(self):
        htmlxml, proc = self._conversion("S0034-89102004000200001")
        with patch("htmlxml.review.review_conversion", side_effect=ValueError("x")):
            self.assertIsNone(htmlxml.review(self.user, proc, {}))

    def test_command(self):
        self._conversion("S0034-89102004000200001")
        self._conversion("S0034-89102004000200002", xml=XML_BAD)
        out = io.StringIO()
        call_command("review_html2xml", stdout=out)
        self.assertIn("Revisadas: 2", out.getvalue())
        self.assertIn("'ok': 1", out.getvalue())
        self.assertIn("'major': 1", out.getvalue())
        out = io.StringIO()
        call_command("review_html2xml", "--only-not-reviewed", stdout=out)
        self.assertIn("Revisadas: 0", out.getvalue())


class BlockingTest(ReviewTestMixin, TestCase):
    def test_blocking_category_blocks_only_that_article(self):
        bad, bad_proc = self._conversion("S0034-89102004000200001", xml=XML_BAD)
        good, good_proc = self._conversion("S0034-89102004000200002")
        review.review_existing(bad)
        review.review_existing(good)
        Html2xmlProblem.objects.update(blocks_publication=True)

        document = Mock(citations=[], record_types=[])
        with patch.object(MigratedArticle, "document", new_callable=PropertyMock, return_value=document), \
                patch.object(HTMLXML, "html_to_xml", return_value={}):
            detail = {}
            with patch.object(HTMLXML, "create_or_update", return_value=bad):
                with self.assertRaises(Html2xmlBlockingIssuesError):
                    bad_proc.get_xml_from_html(self.user, detail)
            self.assertEqual(len(detail["html_to_xml_blocking_issues"]), 1)
            with patch.object(HTMLXML, "create_or_update", return_value=good):
                self.assertTrue(good_proc.get_xml_from_html(self.user, {}).endswith("a.xml"))

    def test_not_blocking_by_default(self):
        bad, bad_proc = self._conversion("S0034-89102004000200001", xml=XML_BAD)
        review.review_existing(bad)
        self.assertFalse(bad.blocking_issues().exists())


class ReviewAdminTest(ReviewTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(username="admin", email="a@example.com", password="x")
        self.client.force_login(self.admin)
        for i, xml in enumerate((XML_BAD, XML_BAD, XML), start=1):
            htmlxml, _ = self._conversion(f"S003489102004000200{i:03d}", xml=xml, html=HTML_LOSS if i == 1 else HTML_CLEAN)
            review.review_existing(htmlxml)

    def _problem(self, check):
        return Html2xmlProblem.objects.get(category__check_code=check)

    def test_problem_list_most_severe_first_with_counts(self):
        response = self.client.get(reverse("wagtailsnippets_htmlxml_html2xmlproblem:list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        text_lost = self._problem("text_lost")
        non_jats = self._problem("non_jats_element")
        # crítico antes de importante
        self.assertLess(content.index(f'?problem={text_lost.pk}"'), content.index(f'?problem={non_jats.pk}"'))
        self.assertIn(f'?problem={non_jats.pk}">2</a>', content)
        # "adicionar" leva ao formulário de solicitação
        self.assertIn(reverse("proc:request_html2xml_review"), content)

    def test_triage_edit(self):
        problem = self._problem("non_jats_element")
        url = reverse("wagtailsnippets_htmlxml_html2xmlproblem:edit", args=[problem.pk])
        response = self.client.post(url, {"status": "converter", "blocks_publication": "on", "note": "abrir issue"})
        self.assertEqual(response.status_code, 302)
        problem.refresh_from_db()
        self.assertEqual((problem.status, problem.blocks_publication, problem.note), ("converter", True, "abrir issue"))

    def test_occurrence_list_and_conversion_filter(self):
        problem = self._problem("text_lost")
        response = self.client.get(reverse("wagtailsnippets_htmlxml_html2xmlissue:list") + f"?problem={problem.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<mark>propuseram")
        response = self.client.get(reverse("wagtailsnippets_htmlxml_htmlxml:list") + "?review_severity=critical")
        self.assertEqual(response.status_code, 200)


class ManagerSetupMixin(ReviewTestMixin):
    """Gestor de "scl"; problemas em "scl" e em "cri"; um membro (não gestor)."""

    def setUp(self):
        super().setUp()
        from team.models import CollectionTeamMember, TeamRole

        self.other = Collection.get_or_create(acron="cri", name="SciELO Costa Rica", user=self.user)
        htmlxml, _ = self._conversion("S0034-89102004000200001", xml=XML_BAD)
        review.review_existing(htmlxml)
        other_htmlxml, other_proc = self._conversion(
            "S1409-00152004000200001", xml=XML_BAD, collection=self.other
        )
        review.review_existing(other_htmlxml)
        self.mine = Html2xmlProblem.objects.get(collection=self.collection)
        self.theirs = Html2xmlProblem.objects.get(collection=self.other)

        self.manager = User.objects.create_user(username="gestor", password="x")
        from django.contrib.auth.models import Permission

        self.manager.user_permissions.add(Permission.objects.get(codename="access_admin"))
        CollectionTeamMember.objects.create(
            user=self.manager, collection=self.collection, role=TeamRole.MANAGER, creator=self.user
        )
        self.member = User.objects.create_user(username="membro", password="x")
        self.member.user_permissions.add(Permission.objects.get(codename="access_admin"))
        CollectionTeamMember.objects.create(
            user=self.member, collection=self.collection, role=TeamRole.MEMBER, creator=self.user
        )


class CollectionManagerTest(ManagerSetupMixin, TestCase):
    """Gestor da coleção: solicita e revisa só as coleções que gerencia."""

    def test_manager_sees_and_edits_only_own_collection(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("wagtailsnippets_htmlxml_html2xmlproblem:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"?problem={self.mine.pk}")
        self.assertNotContains(response, f"?problem={self.theirs.pk}")

        edit = "wagtailsnippets_htmlxml_html2xmlproblem:edit"
        response = self.client.post(reverse(edit, args=[self.mine.pk]), {"status": "data", "note": ""})
        self.assertEqual(response.status_code, 302)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, "data")

        response = self.client.post(reverse(edit, args=[self.theirs.pk]), {"status": "data", "note": ""})
        self.assertNotEqual(response.status_code, 200)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.status, "new")

        response = self.client.get(reverse("wagtailsnippets_htmlxml_html2xmlissue:list"))
        self.assertContains(response, "S0034-89102004000200001")
        self.assertNotContains(response, "S1409-00152004000200001")

    def test_member_without_manager_role_has_no_access(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("proc:request_html2xml_review"))
        # o Wagtail responde à recusa redirecionando, com aviso
        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse("wagtailsnippets_htmlxml_html2xmlproblem:list"))
        self.assertNotEqual(response.status_code, 200)

    @patch("htmlxml.tasks.task_review_html2xml.delay")
    def test_manager_requests_review_of_own_collection(self, mock_delay):
        self.client.force_login(self.manager)
        url = reverse("proc:request_html2xml_review")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="scl"')
        self.assertNotContains(response, 'value="cri"')

        # coleção que não gerencia: recusada
        response = self.client.post(url, {"collection_acron_list": ["cri"]})
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_not_called()

        response = self.client.post(url, {
            "collection_acron_list": ["scl"],
            "journal_acron_list": "rsp",
            "updated_from": "2026-01-01",
            "only_not_reviewed": "on",
        })
        self.assertRedirects(
            response, reverse("wagtailsnippets_htmlxml_html2xmlproblem:list"), fetch_redirect_response=False
        )
        kwargs = mock_delay.call_args.kwargs
        self.assertEqual(kwargs["user_id"], self.manager.id)
        self.assertEqual(kwargs["collection_acron_list"], ["scl"])
        self.assertEqual(kwargs["journal_acron_list"], ["rsp"])
        self.assertEqual(kwargs["updated_from"], "2026-01-01")
        self.assertTrue(kwargs["only_not_reviewed"])

    def test_task_reviews_requested_scope(self):
        from htmlxml.tasks import task_review_html2xml

        Html2xmlIssue.objects.all().delete()
        HTMLXML.objects.update(reviewed_at=None)
        result = task_review_html2xml(user_id=self.manager.id, collection_acron_list=["scl"])
        self.assertEqual(result, {"major": 1})


class CollectionManagerReportTest(ManagerSetupMixin, TestCase):
    """O gestor gera, vê e baixa o relatório CSV de conversão das suas coleções."""

    def _report(self, collections, report_type="html2xml"):
        from proc.models import ProblemReport

        return ProblemReport.create_request(
            {"collection_acron_list": collections}, ["article"], user=self.user,
            report_type=report_type, status=ProblemReport.STATUS_DONE,
        )

    @patch("proc.tasks.task_generate_problem_report.delay")
    def test_manager_generates_html2xml_report_of_own_collection(self, mock_delay):
        from proc.models import ProblemReport

        self.client.force_login(self.manager)
        url = reverse("proc:generate_problem_report")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="html2xml"')
        self.assertNotContains(response, 'value="problems"')
        self.assertContains(response, 'value="scl"')
        self.assertNotContains(response, 'value="cri"')

        data = {"content_type": "articles", "updated_from": "2026-01-01", "max_items": "100"}
        # sem coleção ou com coleção de outro gestor: recusado
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertEqual(self.client.post(url, {**data, "collection_acron_list": ["cri"]}).status_code, 200)
        mock_delay.assert_not_called()

        # o relatório de problemas de migração/publicação não é para o gestor
        response = self.client.post(url, {**data, "collection_acron_list": ["scl"], "report_type": "problems"})
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_not_called()

        response = self.client.post(url, {**data, "collection_acron_list": ["scl"], "report_type": "html2xml"})
        self.assertEqual(response.status_code, 302)
        report = ProblemReport.objects.get(pk=mock_delay.call_args.kwargs["problem_report_id"])
        self.assertEqual(report.report_type, "html2xml")
        self.assertEqual(report.scope["collection_acron_list"], ["scl"])
        self.assertEqual(report.creator, self.manager)

    def test_manager_sees_only_conversion_reports_of_own_collections(self):
        own = self._report(["scl"])
        other = self._report(["cri"])
        mixed = self._report(["cri", "scl"])
        all_collections = self._report([])
        problems = self._report(["scl"], report_type="problems")

        self.client.force_login(self.manager)
        listing = self.client.get(reverse("wagtailsnippets_proc_problemreport:list"))
        self.assertEqual(listing.status_code, 200)
        inspect = "wagtailsnippets_proc_problemreport:inspect"
        self.assertContains(listing, reverse(inspect, args=[own.pk]))
        for report in (other, mixed, all_collections, problems):
            self.assertNotContains(listing, reverse(inspect, args=[report.pk]))

        self.assertEqual(self.client.get(reverse(inspect, args=[own.pk])).status_code, 200)
        for report in (other, mixed, all_collections, problems):
            response = self.client.get(reverse(inspect, args=[report.pk]))
            self.assertNotEqual(response.status_code, 200)

        # apagar continua exclusivo do administrador
        response = self.client.get(reverse("wagtailsnippets_proc_problemreport:delete", args=[own.pk]))
        self.assertNotEqual(response.status_code, 200)
        self.assertTrue(type(own).objects.filter(pk=own.pk).exists())

    def test_member_cannot_use_reports(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("proc:generate_problem_report"))
        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse("wagtailsnippets_proc_problemreport:list"))
        self.assertNotEqual(response.status_code, 200)


class ManagerOfSeveralCollectionsTest(ManagerSetupMixin, TestCase):
    """Gestor de mais de uma coleção: acessa todas que gerencia, só elas."""

    def setUp(self):
        super().setUp()
        from team.models import CollectionTeamMember, TeamRole

        CollectionTeamMember.objects.create(
            user=self.manager, collection=self.other, role=TeamRole.MANAGER, creator=self.user
        )
        # membro (não gestor) de uma terceira e gestor inativo de uma quarta: não contam
        self.third = Collection.get_or_create(acron="arg", name="SciELO Argentina", user=self.user)
        self.fourth = Collection.get_or_create(acron="prt", name="SciELO Portugal", user=self.user)
        CollectionTeamMember.objects.create(
            user=self.manager, collection=self.third, role=TeamRole.MEMBER, creator=self.user
        )
        CollectionTeamMember.objects.create(
            user=self.manager, collection=self.fourth, role=TeamRole.MANAGER,
            is_active_member=False, creator=self.user,
        )
        self.client.force_login(self.manager)

    def test_managed_collections(self):
        from htmlxml.permissions import managed_collections

        self.assertEqual([c.acron for c in managed_collections(self.manager)], ["cri", "scl"])

    def test_sees_and_edits_problems_of_all_managed_collections(self):
        listing = self.client.get(reverse("wagtailsnippets_htmlxml_html2xmlproblem:list"))
        self.assertContains(listing, f"?problem={self.mine.pk}")
        self.assertContains(listing, f"?problem={self.theirs.pk}")
        edit = "wagtailsnippets_htmlxml_html2xmlproblem:edit"
        for problem in (self.mine, self.theirs):
            response = self.client.post(reverse(edit, args=[problem.pk]), {"status": "data", "note": ""})
            self.assertEqual(response.status_code, 302)
            problem.refresh_from_db()
            self.assertEqual(problem.status, "data")

    @patch("htmlxml.tasks.task_review_html2xml.delay")
    @patch("proc.tasks.task_generate_problem_report.delay")
    def test_requests_review_and_report_for_several_collections(self, mock_report, mock_review):
        from proc.models import ProblemReport

        for url in (reverse("proc:request_html2xml_review"), reverse("proc:generate_problem_report")):
            page = self.client.get(url)
            self.assertContains(page, 'value="scl"')
            self.assertContains(page, 'value="cri"')
            self.assertNotContains(page, 'value="arg"')
            self.assertNotContains(page, 'value="prt"')

        response = self.client.post(reverse("proc:request_html2xml_review"), {"collection_acron_list": ["scl", "cri"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sorted(mock_review.call_args.kwargs["collection_acron_list"]), ["cri", "scl"])

        # incluir uma coleção da qual é só membro: recusado
        response = self.client.post(
            reverse("proc:request_html2xml_review"), {"collection_acron_list": ["scl", "arg"]}
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse("proc:generate_problem_report"), {
            "report_type": "html2xml", "content_type": "articles", "updated_from": "2026-01-01",
            "max_items": "100", "collection_acron_list": ["scl", "cri"],
        })
        self.assertEqual(response.status_code, 302)
        report = ProblemReport.objects.get(pk=mock_report.call_args.kwargs["problem_report_id"])
        self.assertEqual(sorted(report.scope["collection_acron_list"]), ["cri", "scl"])
        # o relatório das duas coleções aparece para ele
        listing = self.client.get(reverse("wagtailsnippets_proc_problemreport:list"))
        self.assertContains(listing, reverse("wagtailsnippets_proc_problemreport:inspect", args=[report.pk]))

    def test_report_including_unmanaged_collection_is_not_visible(self):
        from proc.models import ProblemReport

        report = ProblemReport.create_request(
            {"collection_acron_list": ["arg", "scl"]}, ["article"], user=self.user,
            report_type="html2xml", status=ProblemReport.STATUS_DONE,
        )
        listing = self.client.get(reverse("wagtailsnippets_proc_problemreport:list"))
        self.assertNotContains(listing, reverse("wagtailsnippets_proc_problemreport:inspect", args=[report.pk]))
