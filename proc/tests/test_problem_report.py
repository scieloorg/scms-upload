import csv
import io
import tempfile
import zipfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase, override_settings
from django.utils import timezone

from collection.models import Collection
from proc import problem_report as pr
from proc.models import (
    ArticleProc,
    ArticleProcResult,
    IssueProc,
    JournalProc,
    ProblemReport,
)
from proc.tasks import task_generate_problem_report
from tracker import choices as tracker_choices

User = get_user_model()
BLOCKED = tracker_choices.PROGRESS_STATUS_BLOCKED
PENDING = tracker_choices.PROGRESS_STATUS_PENDING
DONE = tracker_choices.PROGRESS_STATUS_DONE

TB = """Traceback (most recent call last):
  File "/app/proc/models.py", line 2540, in get_xml
    xml_with_pre = self.get_xml_from_native(detail)
ValueError: Unable to find xml for S0034-89102004000200001 in /data/abc/v1n2/x.xml
"""


class ExtractSignatureTest(TestCase):
    def test_exception_keys_from_operation_finish(self):
        sig = pr.extract_signature(
            {
                "exception_type": "<class 'ValueError'>",
                "exception_message": "bad pid S0034-89102004000200001",
                "traceback": TB,
            }
        )
        self.assertEqual(sig["exception_type"], "ValueError")
        self.assertEqual(sig["template"], "bad pid <PID>")

    def test_traceback_only(self):
        sig = pr.extract_signature({"anything": {"traceback": TB}})
        self.assertEqual(sig["exception_type"], "ValueError")
        self.assertIn("<PID>", sig["template"])
        self.assertIn("<PATH>", sig["template"])

    def test_same_problem_different_items_same_template(self):
        a = pr.extract_signature({"message": "Issue 12 not found for 1234-5678"})
        b = pr.extract_signature({"message": "Issue 345 not found for 0001-000X"})
        self.assertEqual(a["template"], b["template"])

    def test_plain_string_and_json_string(self):
        self.assertEqual(pr.extract_signature("migrated")["template"], "migrated")
        sig = pr.extract_signature('{"error": "timeout after 30s"}')
        self.assertEqual(sig["template"], "timeout after <N>s")

    def test_nested_list_of_failures(self):
        sig = pr.extract_signature(
            {"response": {"failures": [{"error_type": "KeyError", "msg": "'v880'"}]}}
        )
        self.assertEqual(sig["exception_type"], "KeyError")
        self.assertEqual(sig["template"], "'<V>'")

    def test_unknown_shape_uses_keys(self):
        sig = pr.extract_signature({"b": 1, "a": [1, 2]})
        self.assertEqual(sig["source"], "shape")
        self.assertEqual(sig["template"], "keys: a,b")

    def test_empty(self):
        self.assertEqual(pr.extract_signature(None)["template"], "")
        self.assertEqual(pr.extract_signature({})["source"], "empty")

    def test_select_failed_events_root_and_last(self):
        events = [
            {"name": "get xml", "completed": True},
            {"name": "generate_sps_package", "completed": False},
            {"name": "create or update article", "completed": None},
        ]
        first, last = pr.select_failed_events(events)
        self.assertEqual(first["name"], "generate_sps_package")
        self.assertEqual(last["name"], "create or update article")

    def test_safe_text_never_becomes_formula_nor_invalid_xml(self):
        self.assertEqual(pr.safe_text("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(pr.safe_text("-x"), "'-x")
        self.assertEqual(pr.safe_text("-12"), "-12")
        self.assertEqual(pr.safe_text("a\x00b\x1fc"), "abc")
        self.assertEqual(len(pr.safe_text("x" * 40000)), pr.MAX_CELL)
        self.assertEqual(pr.safe_text(None), "")
        self.assertEqual(pr.safe_text(3), 3)

    def test_all_texts_have_three_languages(self):
        for key, entry in pr.TEXTS.items():
            self.assertEqual(set(entry), {"en", "pt", "es"}, key)
        for lang in pr.LANGUAGES:
            for key in ("sheet_readme", "sheet_items", "sheet_events", "sheet_summary", "sheet_status"):
                self.assertLessEqual(len(pr.t(key, lang)), 31)

    def test_operation_name_is_normalized(self):
        self.assertEqual(
            pr.normalize_operation("register S0034-89102004000200001"),
            "register <PID>",
        )


class ProblemReportGenerationTest(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()

        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )
        self.journal_proc = JournalProc.objects.create(
            collection=self.collection, pid="0034-8910", acron="rsp",
            creator=self.user,
        )
        self.issue_proc = IssueProc.objects.create(
            collection=self.collection,
            journal_proc=self.journal_proc,
            pid="0034-891020040002",
            issue_folder="v38n2",
            files_status=PENDING,
            creator=self.user,
        )
        self.a1 = self._article("S0034-89102004000200001", xml_status=BLOCKED)
        self.a2 = self._article("S0034-89102004000200002", xml_status=BLOCKED)
        self.a3 = self._article("S0034-89102004000200003", sps_pkg_status=PENDING)
        self.ok = self._article("S0034-89102004000200004")

        for item, number in ((self.a1, 1), (self.a2, 2)):
            self._event(item, "get xml", False, {
                "exception_type": "<class 'KeyError'>",
                "exception_message": f"'v{number}'",
            })
            self._event(item, "generate_sps_package", False, {"message": "no xml"})
        self._event(self.a3, "get xml", True, {"file_type": "xml"})
        self._event(self.a3, "generate_sps_package", False, {"weird": {"shape": 1}})

    def tearDown(self):
        self.override.disable()
        self.media.cleanup()

    def _article(self, pid, xml_status=DONE, sps_pkg_status=DONE):
        return ArticleProc.objects.create(
            collection=self.collection,
            issue_proc=self.issue_proc,
            pid=pid,
            migration_status=DONE,
            xml_status=xml_status,
            sps_pkg_status=sps_pkg_status,
            qa_ws_status=DONE,
            public_ws_status=DONE,
            creator=self.user,
        )

    def _event(self, proc, name, completed, detail):
        op = ArticleProcResult.create(self.user, proc, name)
        op.finish(self.user, completed=completed, detail=detail)

    def _zip(self, report):
        from django.conf import settings

        basename = report.file.name.split("/")[-1]
        self.assertTrue(basename.startswith(f"upload-{settings.VERSION}-problems-"), basename)
        self.assertTrue(basename.endswith(f"-{report.language}.zip"))
        with report.file.open("rb") as f:
            return zipfile.ZipFile(io.BytesIO(f.read()))

    def _read_csv(self, report, kind):
        names = self._zip(report).namelist()
        number = pr.FILE_KINDS.index(kind) + 1
        name = next(n for n in names if n.startswith(f"{number}-"))
        self.assertTrue(name.endswith(".csv"))
        raw = self._zip(report).read(name)
        self.assertTrue(raw.startswith("\ufeff".encode("utf-8")))
        text = raw.decode("utf-8-sig")
        self.assertIn("\r\n", text)
        if kind == "readme":
            return list(csv.reader(io.StringIO(text)))
        return list(csv.DictReader(io.StringIO(text)))

    def test_groups_by_root_cause_and_orders_by_frequency(self):
        scope = {"collection_acron_list": ["scl"], "journal_acron_list": ["rsp"]}
        report = ProblemReport.generate(
            scope, ["issue", "article"], user=self.user, language="pt-br"
        )

        self.assertEqual(report.language, "pt")
        self.assertEqual(
            self._zip(report).namelist(),
            [
                "1-itens_com_problemas.csv",
                "2-problemas_por_item.csv",
                "3-resumo_por_categoria.csv",
                "4-status.csv",
                "5-leia_me.csv",
            ],
        )
        self.assertEqual(report.stats["files"], self._zip(report).namelist())
        self.assertEqual(report.total_items, 4)  # issue + 3 artigos

        summary = self._read_csv(report, "summary")
        self.assertEqual(summary[0]["Categoria"], "C001")
        self.assertEqual(summary[0]["Itens"], "2")
        self.assertEqual(summary[0]["Operação"], "get xml")
        self.assertEqual(summary[0]["Exceção"], "KeyError")
        self.assertIn("rsp v38n2 S0034-89102004000200001 (scl)", summary[0]["Exemplos de itens"])

        items = {r["Item"]: r for r in self._read_csv(report, "items")}
        a1 = "rsp v38n2 S0034-89102004000200001 (scl)"
        self.assertEqual(
            sorted(items),
            sorted([
                "rsp v38n2 (scl)",
                a1,
                "rsp v38n2 S0034-89102004000200002 (scl)",
                "rsp v38n2 S0034-89102004000200003 (scl)",
            ]),
        )
        self.assertEqual(items[a1]["Categoria"], "C001")
        self.assertEqual(items[a1]["Causa provável: operação"], "get xml")
        self.assertEqual(items[a1]["Último problema: operação"], "generate_sps_package")
        self.assertEqual(items[a1]["Tipo"], "artigo")
        self.assertEqual(items["rsp v38n2 (scl)"]["Status com problema"], "files_status=PENDING")
        self.assertEqual(items["rsp v38n2 (scl)"]["Natureza"], "sem evento de falha")
        # nenhuma coluna expõe o id do banco
        self.assertFalse(any("id" == str(h).lower() for h in items[a1]))

        events = [r for r in self._read_csv(report, "events") if r["Item"] == a1]
        self.assertEqual([e["Operação"] for e in events], ["get xml", "generate_sps_package"])
        self.assertEqual([e["Nº"] for e in events], ["1", "2"])
        self.assertEqual(events[0]["Mensagem"], "'v1'")

        readme = self._read_csv(report, "readme")
        self.assertEqual(readme[0], ["Relatório de problemas de migração/publicação"])

    def test_generates_only_in_requested_language(self):
        for code, lang, title, type_label in (
            ("en", "en", "1-items_with_problems.csv", "issue"),
            ("es", "es", "1-items_con_problemas.csv", "número"),
            ("pt-BR", "pt", "1-itens_com_problemas.csv", "fascículo"),
            ("fr", "en", "1-items_with_problems.csv", "issue"),  # sem suporte: inglês
        ):
            report = ProblemReport.generate(
                {"collection_acron_list": ["scl"]}, ["issue", "article"], language=code,
            )
            self.assertEqual(report.language, lang)
            names = self._zip(report).namelist()
            self.assertEqual(len(names), 5)
            self.assertEqual(names[0], title)
            first_column = {"en": "Item", "pt": "Item", "es": "Ítem"}[lang]
            type_column = {"en": "Type", "pt": "Tipo", "es": "Tipo"}[lang]
            rows = {r[first_column]: r for r in self._read_csv(report, "items")}
            self.assertEqual(rows["rsp v38n2 (scl)"][type_column], type_label)

    def test_language_from_user_preference(self):
        from wagtail.users.models import UserProfile

        profile = UserProfile.get_for_user(self.user)
        profile.preferred_language = "es"
        profile.save()
        self.user.refresh_from_db()
        report = ProblemReport.create_request({"collection_acron_list": ["scl"]}, ["article"], user=self.user)
        self.assertEqual(report.language, "es")

    def test_language_fallback_is_system_language(self):
        with override_settings(LANGUAGE_CODE="pt-BR"):
            from django.utils import translation

            with translation.override(None):
                self.assertEqual(pr.resolve_language(), "pt")

    def test_resolve_language(self):
        self.assertEqual(pr.resolve_language("pt-br"), "pt")
        self.assertEqual(pr.resolve_language("pt_PT"), "pt")
        self.assertEqual(pr.resolve_language("es-ES"), "es")
        self.assertEqual(pr.resolve_language("ru-RU"), "en")

    def test_download_links(self):
        report = ProblemReport.generate(
            {"collection_acron_list": ["scl"]}, ["article"], language="pt"
        )
        html = str(report.download())
        self.assertIn(report.file.url, html)
        self.assertIn(".zip", html)
        self.assertEqual(html.count("<a "), 1)

    def test_deleting_report_removes_files_from_storage(self):
        import os

        report = ProblemReport.generate({"collection_acron_list": ["scl"]}, ["article"])
        paths = [report.file.path]
        self.assertTrue(all(os.path.exists(p) for p in paths))
        report.delete()
        self.assertFalse(any(os.path.exists(p) for p in paths))

    def test_filename_prefix(self):
        with override_settings(VERSION="v2.14.0"):
            self.assertEqual(ProblemReport.filename_prefix(), "upload-v2.14.0-")
        with override_settings(VERSION="v3.0 rc/1"):
            self.assertEqual(ProblemReport.filename_prefix(), "upload-v3.0_rc_1-")
        with override_settings(VERSION=""):
            self.assertEqual(ProblemReport.filename_prefix(), "upload-")

    def test_item_name(self):
        self.assertEqual(pr.item_name("journal", "scl", "rsp", "", "0034-8910"), "rsp (scl)")
        self.assertEqual(pr.item_name("issue", "scl", "rsp", "v38n2", "x"), "rsp v38n2 (scl)")
        self.assertEqual(
            pr.item_name("article", "scl", "rsp", "v38n2", None, "pkg-1"),
            "rsp v38n2 pkg-1 (scl)",
        )

    def test_scope_filters_other_journals(self):
        scope = {"collection_acron_list": ["scl"], "journal_acron_list": ["other"]}
        report = ProblemReport.generate(scope, ["issue", "article"])
        self.assertEqual(report.total_items, 0)

    def test_new_report_replaces_previous_of_same_scope_and_purges_expired(self):
        scope = {"collection_acron_list": ["scl"]}
        old = ProblemReport.generate(scope, ["article"])
        other = ProblemReport.generate({"collection_acron_list": ["x"]}, ["article"])
        ProblemReport.objects.filter(pk=other.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )
        new = ProblemReport.generate(scope, ["article"])
        self.assertEqual(list(ProblemReport.objects.values_list("pk", flat=True)), [new.pk])
        self.assertNotEqual(old.pk, new.pk)

    @patch("proc.tasks.task_generate_problem_report.apply_async")
    def test_task_waits_while_scope_is_busy(self, mock_apply_async):
        result = task_generate_problem_report(
            content_type="articles",
            collection_acron="scl",
            wait_until_idle=True,
            quiet_minutes=15,
        )
        self.assertTrue(result["rescheduled"])
        mock_apply_async.assert_called_once()
        # o registro já existe, visível no admin, aguardando
        report = ProblemReport.objects.get(pk=result["problem_report_id"])
        self.assertEqual(report.status, ProblemReport.STATUS_WAITING)
        self.assertTrue(report.in_progress)
        self.assertFalse(report.file)
        self.assertEqual(
            mock_apply_async.call_args.kwargs["kwargs"]["problem_report_id"], report.id
        )

    @patch("proc.tasks.task_generate_problem_report.apply_async")
    def test_task_generates_when_deadline_reached(self, mock_apply_async):
        result = task_generate_problem_report(
            content_type="articles",
            collection_acron="scl",
            wait_until_idle=True,
            first_attempt_at=(timezone.now() - timedelta(hours=48)).isoformat(),
        )
        mock_apply_async.assert_not_called()
        report = ProblemReport.objects.get(pk=result["problem_report_id"])
        self.assertEqual(report.total_items, 4)
        self.assertEqual(report.status, ProblemReport.STATUS_DONE)
        self.assertIsNotNone(report.generated_at)

    def test_task_uses_requested_record_and_marks_done(self):
        scope = {"collection_acron_list": ["scl"], "journal_acron_list": [],
                 "publication_year": None, "issue_folder": None}
        requested = ProblemReport.create_request(scope, ["issue", "article"])
        self.assertEqual(requested.status, ProblemReport.STATUS_QUEUED)
        self.assertIn("reload", str(requested.download()))

        result = task_generate_problem_report(
            content_type="articles", collection_acron="scl",
            problem_report_id=requested.id,
        )
        self.assertEqual(result["problem_report_id"], requested.id)
        requested.refresh_from_db()
        self.assertEqual(requested.status, ProblemReport.STATUS_DONE)
        self.assertEqual(requested.total_items, 4)
        self.assertIn("download", requested.download())

    def test_task_cancelled_when_request_was_deleted(self):
        result = task_generate_problem_report(problem_report_id=999999)
        self.assertEqual(result, {"cancelled": True})
        self.assertFalse(ProblemReport.objects.exists())

    @patch("proc.problem_report.build_report", side_effect=RuntimeError("boom"))
    def test_error_status_is_recorded(self, _build):
        report = ProblemReport.create_request({"collection_acron_list": ["scl"]}, ["article"])
        with self.assertRaises(RuntimeError):
            report.run()
        report.refresh_from_db()
        self.assertEqual(report.status, ProblemReport.STATUS_ERROR)
        self.assertIn("boom", report.error)

    def test_stale_generating_report_is_marked_as_error(self):
        report = ProblemReport.create_request({"collection_acron_list": ["scl"]}, ["article"])
        report.set_status(ProblemReport.STATUS_GENERATING)
        self.assertEqual(ProblemReport.mark_stale(), 0)  # ainda dentro do limite
        ProblemReport.objects.filter(pk=report.pk).update(
            updated=timezone.now()
            - timedelta(seconds=ProblemReport.generation_time_limit() + 301)
        )
        self.assertEqual(ProblemReport.mark_stale(), 1)
        report.refresh_from_db()
        self.assertEqual(report.status, ProblemReport.STATUS_ERROR)
        self.assertIn("interrupted", report.error)

    def test_soft_time_limit_marks_error_with_hint(self):
        from celery.exceptions import SoftTimeLimitExceeded

        report = ProblemReport.create_request({"collection_acron_list": ["scl"]}, ["article"])
        with patch("proc.problem_report.build_report", side_effect=SoftTimeLimitExceeded()):
            with self.assertRaises(SoftTimeLimitExceeded):
                report.run()
        report.refresh_from_db()
        self.assertEqual(report.status, ProblemReport.STATUS_ERROR)
        self.assertIn("narrow the scope", report.error)

    def test_task_has_own_time_limits(self):
        self.assertEqual(
            task_generate_problem_report.soft_time_limit,
            ProblemReport.generation_time_limit(),
        )
        self.assertGreater(
            task_generate_problem_report.time_limit,
            task_generate_problem_report.soft_time_limit,
        )

    def test_only_failed_events_are_read(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            pr.collect_problems({"collection_acron_list": ["scl"]}, ["article"])
        event_queries = [q["sql"] for q in ctx.captured_queries if "proc_operation" in q["sql"]]
        self.assertTrue(event_queries)
        self.assertTrue(all('"completed"' in q for q in event_queries))

    # ---- período de atualização (aplicado antes de tudo) ----

    def _age(self, proc, days):
        type(proc).objects.filter(pk=proc.pk).update(
            updated=timezone.now() - timedelta(days=days)
        )

    def test_updated_range_parsing(self):
        start, end = pr.updated_range({"updated_from": "2026-11-01", "updated_to": "2026-11-10"})
        self.assertEqual((start.year, start.month, start.day, start.hour), (2026, 11, 1, 0))
        # data final inclusiva: vai até o início do dia seguinte (exclusivo)
        self.assertEqual((end.year, end.month, end.day, end.hour), (2026, 11, 11, 0))
        start, end = pr.updated_range({"updated_from": "2026-11-16T10:30:00+00:00"})
        self.assertEqual((start.hour, start.minute), (10, 30))
        self.assertIsNone(end)
        self.assertEqual(pr.updated_range({}), (None, None))

    def test_period_limits_items_overview_and_sample(self):
        self._age(self.a1, 30)
        self._age(self.issue_proc, 30)
        scope = {
            "collection_acron_list": ["scl"],
            "updated_from": (timezone.localdate() - timedelta(days=7)).isoformat(),
        }
        report = ProblemReport.generate(scope, ["issue", "article"], language="en")
        items = sorted(r["Item"] for r in self._read_csv(report, "items"))
        self.assertEqual(items, [
            "rsp v38n2 S0034-89102004000200002 (scl)",
            "rsp v38n2 S0034-89102004000200003 (scl)",
        ])
        self.assertEqual(report.stats["coverage"]["article"], {"total": 2, "processed": 2})
        self.assertEqual(report.stats["coverage"]["issue"], {"total": 0, "processed": 0})
        # a contagem de status também respeita o período (3 de 4 artigos; 0 fascículos)
        status = self._read_csv(report, "status")
        xml = {r["Status"]: int(r["Total"]) for r in status if r["Status field"] == "xml_status"}
        self.assertEqual(sum(xml.values()), 3)
        self.assertFalse([r for r in status if r["Type"] == "issue"])
        # leia-me e rótulo mostram o período
        readme = self._read_csv(report, "readme")
        self.assertIn(["Items updated between", f"{scope['updated_from']} — …"], readme)
        self.assertIn(f"({scope['updated_from']}..)", report.scope_label)

    def test_period_end_is_inclusive(self):
        self._age(self.a2, 3)
        day = (timezone.now() - timedelta(days=3)).date().isoformat()
        scope = {"collection_acron_list": ["scl"], "updated_from": day, "updated_to": day}
        rows = pr.collect_problems(scope, ["article"])["rows"]
        self.assertEqual([r["pid"] for r in rows], [self.a2.pid])

    def test_reports_with_different_periods_replace_each_other(self):
        base = {"collection_acron_list": ["scl"]}
        old = ProblemReport.generate({**base, "updated_from": "2026-01-01"}, ["article"])
        new = ProblemReport.generate({**base, "updated_from": "2026-11-01"}, ["article"])
        self.assertEqual(list(ProblemReport.objects.values_list("pk", flat=True)), [new.pk])
        self.assertNotEqual(old.pk, new.pk)

    @patch("proc.tasks.task_generate_problem_report.apply_async")
    def test_waiting_task_keeps_the_period_when_rescheduled(self, mock_apply_async):
        since = (timezone.localdate() - timedelta(days=1)).isoformat()
        result = task_generate_problem_report(
            content_type="articles", collection_acron="scl", wait_until_idle=True,
            updated_from=since,
        )
        self.assertTrue(result["rescheduled"])
        kwargs = mock_apply_async.call_args.kwargs["kwargs"]
        self.assertEqual((kwargs["updated_from"], kwargs["updated_to"]), (since, None))

    @patch("proc.tasks.task_generate_problem_report.apply_async")
    def test_period_in_the_past_does_not_wait(self, mock_apply_async):
        # nada do período está em andamento: gera na hora
        result = task_generate_problem_report(
            content_type="articles", collection_acron="scl", wait_until_idle=True,
            updated_from="2020-01-01", updated_to="2020-01-31",
        )
        mock_apply_async.assert_not_called()
        self.assertIn("problem_report_id", result)

    # ---- tudo do período; limite = quantidade de problemas (capacidade) ----

    def test_all_items_of_the_period_including_without_failure_events(self):
        report = ProblemReport.generate(
            {"collection_acron_list": ["scl"]}, ["issue", "article"], language="pt"
        )
        self.assertEqual(report.status, ProblemReport.STATUS_DONE)
        items = {r["Item"]: r for r in self._read_csv(report, "items")}
        self.assertEqual(sorted(items), sorted([
            "rsp v38n2 (scl)",
            "rsp v38n2 S0034-89102004000200001 (scl)",
            "rsp v38n2 S0034-89102004000200002 (scl)",
            "rsp v38n2 S0034-89102004000200003 (scl)",
        ]))
        self.assertEqual(items["rsp v38n2 (scl)"]["Natureza"], "sem evento de falha")
        self.assertEqual(report.coverage(), "4 / 4 (100%)")

    def test_when_capped_the_most_recently_updated_are_kept(self):
        # do mais antigo ao mais novo: a1, a3, a2
        self._age(self.a1, 4)
        self._age(self.a3, 2)
        self._age(self.a2, 1)
        report = ProblemReport.generate(
            {"collection_acron_list": ["scl"]}, ["article"], language="en", max_items=2
        )
        self.assertEqual(report.status, ProblemReport.STATUS_PARTIAL)
        items = [r["Item"] for r in self._read_csv(report, "items")]
        self.assertEqual(sorted(items), [
            "rsp v38n2 S0034-89102004000200002 (scl)",
            "rsp v38n2 S0034-89102004000200003 (scl)",
        ])
        self.assertEqual(report.coverage(), "2 / 3 (66%)")
        self.assertIn("older items of the period were not analyzed", report.notice)

    def test_types_are_interleaved_by_update_date_when_capped(self):
        # fascículo mais antigo que os artigos: as vagas ficam com os artigos
        self._age(self.issue_proc, 5)
        report = ProblemReport.generate(
            {"collection_acron_list": ["scl"]}, ["issue", "article"], language="en", max_items=2
        )
        self.assertEqual(report.stats["coverage"]["issue"], {"total": 1, "processed": 0})
        self.assertEqual(report.stats["coverage"]["article"], {"total": 3, "processed": 2})
        # fascículo mais recente que todos: entra primeiro
        self._age(self.a1, 3)
        self._age(self.a2, 3)
        self._age(self.a3, 3)
        ProblemReport.objects.all().delete()
        IssueProc.objects.filter(pk=self.issue_proc.pk).update(updated=timezone.now())
        report = ProblemReport.generate(
            {"collection_acron_list": ["scl"]}, ["issue", "article"], language="en", max_items=2
        )
        self.assertEqual(report.stats["coverage"]["issue"], {"total": 1, "processed": 1})
        self.assertEqual(report.stats["coverage"]["article"], {"total": 3, "processed": 1})

    def test_any_old_date_is_accepted(self):
        from proc.forms import ProblemReportRequestForm

        form = ProblemReportRequestForm(
            data={"content_type": "articles", "updated_from": "2000-01-01", "max_items": 10}
        )
        self.assertTrue(form.is_valid(), form.errors)
        report = ProblemReport.generate(
            {"collection_acron_list": ["scl"], "updated_from": "2000-01-01"}, ["issue", "article"]
        )
        self.assertEqual(report.total_items, 4)

    def test_max_items_is_informed_per_request_with_default(self):
        report = ProblemReport.create_request({"collection_acron_list": ["scl"]}, ["article"])
        self.assertEqual(report.max_items, ProblemReport.DEFAULT_MAX_ITEMS)
        report = ProblemReport.create_request(
            {"collection_acron_list": ["scl"]}, ["article"], max_items=50
        )
        self.assertEqual(report.max_items, 50)

    def test_memory_limit_gives_partial_report(self):
        with patch("proc.problem_report.current_memory_mb", return_value=5000.0), \
                override_settings(PROBLEM_REPORT_MEMORY_LIMIT_MB=100):
            report = ProblemReport.generate(
                {"collection_acron_list": ["scl"]}, ["issue", "article"], language="es"
            )
        self.assertEqual(report.status, ProblemReport.STATUS_PARTIAL)
        self.assertEqual(report.stats["partial"]["reason"], pr.PARTIAL_MEMORY)
        self.assertEqual(report.total_items, 0)
        self.assertIn("INFORME INCOMPLETO", report.notice)
        self.assertIn("memoria disponible", report.notice)
        self.assertEqual(report.coverage(), "0 / 4 (0%)")

    def test_memory_limit_resolution(self):
        with override_settings(PROBLEM_REPORT_MEMORY_LIMIT_MB=300):
            self.assertEqual(pr.memory_limit_mb(), 300)
        with patch("proc.problem_report._cgroup_memory_limit_mb", return_value=2560.0):
            self.assertEqual(pr.memory_limit_mb(), 1280)
        with patch("proc.problem_report._cgroup_memory_limit_mb", return_value=None):
            self.assertEqual(pr.memory_limit_mb(), pr.DEFAULT_MEMORY_LIMIT_MB)
        self.assertGreater(pr.current_memory_mb(), 0)

    # ---- relatório incompleto é melhor que nenhum ----

    def test_max_items_reached_gives_partial_report(self):
        report = ProblemReport.generate(
            {"collection_acron_list": ["scl"]}, ["issue", "article"], language="pt", max_items=2
        )
        self.assertEqual(report.status, ProblemReport.STATUS_PARTIAL)
        self.assertEqual(report.total_items, 2)
        self.assertEqual(report.stats["partial"]["reason"], pr.PARTIAL_ITEMS)
        # os artigos (criados depois do fascículo) são os mais recentes
        self.assertEqual(report.stats["coverage"]["issue"], {"total": 1, "processed": 0})
        self.assertEqual(report.stats["coverage"]["article"], {"total": 3, "processed": 2})
        self.assertIn("RELATÓRIO INCOMPLETO", report.notice)
        self.assertIn("Analisados (artigo): 2 de 3", report.notice)
        self.assertIn("Analisados (fascículo): 0 de 1", report.notice)
        # pode ser baixado e o leia-me avisa
        self.assertIn(report.file.url, str(report.download()))
        readme = self._read_csv(report, "readme")
        self.assertEqual(readme[2][0], "RELATÓRIO INCOMPLETO")
        self.assertIn(["Analisados: artigo", "2 de 3"], readme)
        self.assertEqual(len(self._read_csv(report, "items")), 2)

    def test_time_budget_exhausted_still_produces_report(self):
        fileobj, stats = pr.build_report(
            {"collection_acron_list": ["scl"]}, ["issue", "article"], language="en", time_budget=0
        )
        with fileobj:
            names = zipfile.ZipFile(fileobj).namelist()
        self.assertEqual(len(names), 5)
        self.assertEqual(stats["partial"]["reason"], pr.PARTIAL_TIME)
        self.assertEqual(stats["total_items"], 0)
        self.assertEqual(stats["coverage"]["issue"], {"total": 1, "processed": 0})
        self.assertEqual(stats["coverage"]["article"], {"total": 3, "processed": 0})

    def test_celery_soft_time_limit_during_collection_keeps_what_was_collected(self):
        from celery.exceptions import SoftTimeLimitExceeded

        original = pr._collect_chunk
        calls = {"n": 0}

        def chunk_then_timeout(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise SoftTimeLimitExceeded()
            return original(*args, **kwargs)

        with patch("proc.problem_report._collect_chunk", side_effect=chunk_then_timeout):
            report = ProblemReport.generate(
                {"collection_acron_list": ["scl"]}, ["issue", "article"], language="en",
            )
        self.assertEqual(report.status, ProblemReport.STATUS_PARTIAL)
        self.assertEqual(report.stats["partial"]["reason"], pr.PARTIAL_TIME)
        self.assertEqual(report.total_items, 3)  # os artigos, os mais recentes do lote
        self.assertIn("INCOMPLETE REPORT", report.notice)

    def test_database_error_in_a_batch_gives_partial_report(self):
        original = pr._collect_chunk
        calls = {"n": 0}

        def chunk_then_fail(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("connection lost")
            return original(*args, **kwargs)

        with patch("proc.problem_report._collect_chunk", side_effect=chunk_then_fail):
            report = ProblemReport.generate(
                {"collection_acron_list": ["scl"]}, ["issue", "article"], language="en",
            )
        self.assertEqual(report.status, ProblemReport.STATUS_PARTIAL)
        self.assertEqual(report.stats["partial"]["reason"], pr.PARTIAL_ERROR)
        self.assertIn("RuntimeError: connection lost", report.notice)

    def test_error_analyzing_one_item_does_not_stop_the_report(self):
        original = pr._event_signature

        def fail_for_one(event):
            # só o evento "get xml" do artigo 1 (exception_message "'v1'")
            if event["name"] == "get xml" and event["detail"].get("exception_message") == "'v1'":
                raise ValueError("unexpected detail")
            return original(event)

        with patch("proc.problem_report._event_signature", side_effect=fail_for_one):
            report = ProblemReport.generate(
                {"collection_acron_list": ["scl"]}, ["issue", "article"], language="en",
            )
        self.assertEqual(report.status, ProblemReport.STATUS_DONE)
        self.assertEqual(report.total_items, 4)
        items = {r["Item"]: r for r in self._read_csv(report, "items")}
        a1 = items["rsp v38n2 S0034-89102004000200001 (scl)"]
        self.assertEqual(a1["Nature"], "could not be analyzed")
        self.assertIn("ValueError: unexpected detail", a1["Probable cause: message"])
        self.assertEqual(
            items["rsp v38n2 S0034-89102004000200002 (scl)"]["Nature"], "exception (likely bug)"
        )

    def test_complete_report_has_no_notice(self):
        report = ProblemReport.generate({"collection_acron_list": ["scl"]}, ["issue", "article"])
        self.assertEqual(report.status, ProblemReport.STATUS_DONE)
        self.assertIsNone(report.notice)
        self.assertIsNone(report.stats["partial"])

    def test_pending_request_is_not_replaced_by_older_finished_one(self):
        scope = {"collection_acron_list": ["scl"]}
        done = ProblemReport.generate(scope, ["article"])
        pending = ProblemReport.create_request(scope, ["article"])
        ProblemReport.generate(scope, ["article"])
        ids = set(ProblemReport.objects.values_list("pk", flat=True))
        self.assertNotIn(done.pk, ids)
        self.assertIn(pending.pk, ids)


class ScheduleFromEntryTasksTest(TestCase):
    @patch("proc.tasks.task_generate_problem_report.apply_async")
    @patch("proc.tasks.task_migrate_and_publish_journals_by_collection")
    @patch("proc.tasks._get_collections", return_value=[])
    def test_journals_entry_task_schedules_report(self, _c, _by_collection, mock_apply):
        from proc.tasks import task_migrate_and_publish_journals

        task_migrate_and_publish_journals(
            collection_acron="scl", journal_acron="rsp", problem_report_max_items=2000
        )
        kwargs = mock_apply.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["content_type"], "journals")
        self.assertEqual(kwargs["collection_acron"], "scl")
        self.assertTrue(kwargs["wait_until_idle"])
        report = ProblemReport.objects.get(pk=kwargs["problem_report_id"])
        self.assertEqual(report.status, ProblemReport.STATUS_WAITING)
        self.assertEqual(report.scope["journal_acron_list"], ["rsp"])
        self.assertEqual(report.max_items, 2000)
        # automático: itens atualizados desde o início da execução
        self.assertTrue(kwargs["updated_from"])
        self.assertEqual(report.scope["updated_from"], kwargs["updated_from"])
        started = timezone.datetime.fromisoformat(kwargs["updated_from"])
        self.assertLess(abs((timezone.now() - started).total_seconds()), 60)

    @patch("proc.tasks.task_generate_problem_report.apply_async")
    @patch("proc.tasks._get_collections", return_value=[])
    def test_can_be_disabled(self, _c, mock_apply):
        from proc.tasks import task_migrate_and_publish_issues

        task_migrate_and_publish_issues(collection_acron="scl", generate_problem_report=False)
        mock_apply.assert_not_called()


class OnDemandProblemReportTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin", email="a@example.com", password="x"
        )
        Collection.get_or_create(acron="scl", name="SciELO Brasil", user=self.admin)
        self.client.force_login(self.admin)

    def test_list_shows_generate_button(self):
        response = self.client.get(reverse("wagtailsnippets_proc_problemreport:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("proc:generate_problem_report"))

    def test_add_redirects_to_generate_form(self):
        response = self.client.get(reverse("wagtailsnippets_proc_problemreport:add"))
        self.assertRedirects(
            response, reverse("proc:generate_problem_report"), fetch_redirect_response=False
        )

    def test_form_renders(self):
        response = self.client.get(reverse("proc:generate_problem_report"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="scl"')
        self.assertContains(response, 'name="updated_from"')
        self.assertContains(response, 'name="updated_to"')

    def test_form_default_period_and_validation(self):
        from proc.forms import ProblemReportRequestForm

        form = ProblemReportRequestForm()
        self.assertEqual(
            form.fields["updated_from"].initial,
            timezone.localdate() - timedelta(days=ProblemReportRequestForm.DEFAULT_PERIOD_DAYS),
        )
        form = ProblemReportRequestForm(data={
            "content_type": "articles",
            "updated_from": "2026-11-10", "updated_to": "2026-11-01",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("updated_to", form.errors)
        # "a partir de" e o máximo de itens são obrigatórios
        form = ProblemReportRequestForm(data={"content_type": "articles"})
        self.assertFalse(form.is_valid())
        self.assertIn("updated_from", form.errors)
        self.assertIn("max_items", form.errors)
        self.assertEqual(
            ProblemReportRequestForm().fields["max_items"].initial, ProblemReport.DEFAULT_MAX_ITEMS
        )
        form = ProblemReportRequestForm(data={
            "content_type": "articles", "updated_from": "2026-11-01", "max_items": 0,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("max_items", form.errors)

    @patch("proc.tasks.task_generate_problem_report.delay")
    def test_post_schedules_immediate_report(self, mock_delay):
        response = self.client.post(
            reverse("proc:generate_problem_report"),
            {
                "content_type": "all",
                "collection_acron_list": ["scl"],
                "journal_acron_list": "rsp, bjmbr",
                "publication_year": "2004",
                "issue_folder": "",
                "updated_from": "2026-11-01",
                "updated_to": "2026-11-15",
                "max_items": "300",
            },
            HTTP_ACCEPT_LANGUAGE="es",
        )
        self.assertRedirects(
            response,
            reverse("wagtailsnippets_proc_problemreport:list"),
            fetch_redirect_response=False,
        )
        kwargs = mock_delay.call_args.kwargs
        self.assertEqual(kwargs["content_type"], "all")
        self.assertEqual(kwargs["collection_acron_list"], ["scl"])
        self.assertEqual(kwargs["journal_acron_list"], ["bjmbr", "rsp"])
        self.assertEqual(kwargs["publication_year"], "2004")
        self.assertNotIn("wait_until_idle", kwargs)
        report = ProblemReport.objects.get(pk=kwargs["problem_report_id"])
        self.assertEqual(report.status, ProblemReport.STATUS_QUEUED)
        self.assertEqual(report.creator, self.admin)
        # idioma em uso no admin
        self.assertEqual(report.language, "es")
        # período informado no formulário
        self.assertEqual((kwargs["updated_from"], kwargs["updated_to"]), ("2026-11-01", "2026-11-15"))
        self.assertEqual(report.scope["updated_from"], "2026-11-01")
        self.assertEqual(report.scope["updated_to"], "2026-11-15")
        # máximo informado pelo administrador
        self.assertEqual(kwargs["max_items"], 300)
        self.assertEqual(report.max_items, 300)

        listing = self.client.get(
            reverse("wagtailsnippets_proc_problemreport:list"), HTTP_ACCEPT_LANGUAGE="en"
        )
        self.assertContains(listing, "Queued")

    def test_management_command_generates_now(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            out = io.StringIO()
            call_command("generate_problem_report", "--collection", "scl", "--content-type", "all", stdout=out)
            self.assertIn("0 itens", out.getvalue())
            self.assertEqual(ProblemReport.objects.count(), 1)

    def test_list_and_inspect_show_download_only(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            report = ProblemReport.generate({"collection_acron_list": ["scl"]}, ["article"])
            edit_url = reverse("wagtailsnippets_proc_problemreport:edit", args=[report.pk])
            inspect_url = reverse("wagtailsnippets_proc_problemreport:inspect", args=[report.pk])

            listing = self.client.get(reverse("wagtailsnippets_proc_problemreport:list"))
            self.assertEqual(listing.status_code, 200)
            self.assertContains(listing, report.file.url)
            # o título leva ao detalhe, não ao formulário de edição
            self.assertContains(listing, f'href="{inspect_url}"')
            self.assertNotContains(listing, edit_url)

            detail = self.client.get(inspect_url)
            self.assertEqual(detail.status_code, 200)
            self.assertContains(detail, report.file.url)
            self.assertNotContains(detail, edit_url)
            self.assertNotContains(detail, "<form")

            # quem acessar a URL de edição vai para o detalhe
            response = self.client.get(edit_url)
            self.assertRedirects(response, inspect_url, fetch_redirect_response=False)
            response = self.client.post(edit_url, {"scope_label": "x"})
            self.assertRedirects(response, inspect_url, fetch_redirect_response=False)
            report.refresh_from_db()
            self.assertNotEqual(report.scope_label, "x")

    def test_only_administrators_can_use_problem_reports(self):
        from django.contrib.auth.models import Group, Permission

        staff = User.objects.create_user(username="editor", password="x")
        # usuário com acesso ao admin e até com permissões do modelo
        staff.user_permissions.add(
            Permission.objects.get(codename="access_admin"),
            *Permission.objects.filter(content_type__app_label="proc", codename__endswith="problemreport"),
        )
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            report = ProblemReport.generate({"collection_acron_list": ["scl"]}, ["article"])
            self.client.force_login(staff)
            urls = [
                reverse("wagtailsnippets_proc_problemreport:list"),
                reverse("wagtailsnippets_proc_problemreport:inspect", args=[report.pk]),
                reverse("wagtailsnippets_proc_problemreport:delete", args=[report.pk]),
                reverse("proc:generate_problem_report"),
            ]
            for url in urls:
                response = self.client.get(url)
                self.assertIn(response.status_code, (302, 403), url)
                if response.status_code == 302:
                    self.assertNotIn("problemreport", response["Location"], url)
            # nem aparece no menu
            home = self.client.get(reverse("wagtailadmin_home"))
            self.assertNotContains(home, reverse("wagtailsnippets_proc_problemreport:list"))

            # o administrador (superusuário) acessa tudo
            self.client.force_login(self.admin)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 200, url)
