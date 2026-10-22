from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection, WebSiteConfiguration
from package.models import SPSPkg
from proc import tasks
from proc.models import ArticleProc, IssueProc, JournalProc
from tracker.models import TaskTracker


class MigratedArticlePublicationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="publication-review")
        collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )
        journal = JournalProc.objects.create(creator=self.user, collection=collection)
        self.issue = IssueProc.objects.create(
            creator=self.user, collection=collection, journal_proc=journal
        )
        other_issue = IssueProc.objects.create(
            creator=self.user, collection=collection, journal_proc=journal
        )
        self.records = [
            ArticleProc.objects.create(
                creator=self.user,
                collection=collection,
                issue_proc=issue,
                sps_pkg=SPSPkg.objects.create(creator=self.user, pid_v3=f"V3-{index}"),
            )
            for index, issue in enumerate((self.issue, self.issue, other_issue))
        ]
        for purpose in ("QA", "PUBLIC", "OTHER"):
            WebSiteConfiguration.objects.create(
                creator=self.user, collection=collection, purpose=purpose, enabled=True
            )

    def test_publication_limits_explicit_list_and_preserves_standalone_flow(self):
        selected, omitted, other = self.records
        with patch.object(tasks, "_get_user", return_value=self.user), patch.object(
            tasks, "fix_publication_status"
        ), patch.object(
            WebSiteConfiguration, "get_data", return_value={}
        ), patch.object(
            tasks, "task_publish_article"
        ) as publish, patch.object(
            tasks.task_sync_issue, "delay"
        ):
            for ids, expected in (
                (None, [selected.pk, omitted.pk]),
                ([], []),
                ([selected.pk, other.pk], [selected.pk]),
            ):
                with self.subTest(ids=ids):
                    publish.reset_mock()
                    tasks.task_publish_issue_articles.run(
                        issue_proc_id=self.issue.pk, articleprocs_id_list=ids
                    )
                    self.assertCountEqual(
                        [
                            (
                                call.kwargs["article_proc_id"],
                                call.kwargs["website_kind"],
                            )
                            for call in publish.call_args_list
                        ],
                        [
                            (pk, purpose)
                            for pk in expected
                            for purpose in ("QA", "PUBLIC")
                        ],
                    )
                    report = TaskTracker.objects.first()
                    self.assertTrue(report.completed)
                    summary = report.detail["events"][-1]["websites"]
                    self.assertEqual(
                        {item["purpose"] for item in summary}, {"QA", "PUBLIC"}
                    )

    def test_migration_schedules_only_articles_returned_by_migrate_article(self):
        selected, omitted, _ = self.records
        with patch.object(tasks, "_get_user", return_value=self.user), patch.object(
            ArticleProc,
            "migrate_article",
            autospec=True,
            side_effect=lambda proc, user, force: object()
            if proc.pk == selected.pk
            else None,
        ), patch.object(tasks.task_publish_issue_articles, "delay") as schedule:
            tasks.task_migrate_and_publish_articles_by_issue.run(
                issue_proc_id=self.issue.pk,
                article_proc_id_list=[selected.pk, omitted.pk],
            )

        self.assertEqual(
            schedule.call_args.kwargs["articleprocs_id_list"], [selected.pk]
        )
        self.assertEqual(TaskTracker.objects.first().total_processed, 1)

    def test_failure_preserves_publication_summary_and_counters(self):
        with patch.object(tasks, "_get_user", return_value=self.user), patch.object(
            tasks, "fix_publication_status"
        ), patch.object(
            WebSiteConfiguration, "get_data", return_value={}
        ), patch.object(
            tasks, "task_publish_article", side_effect=ValueError("publication failed")
        ), patch.object(
            tasks.task_sync_issue, "delay", side_effect=ValueError("broker unavailable")
        ):
            tasks.task_publish_issue_articles.run(
                issue_proc_id=self.issue.pk, articleprocs_id_list=[self.records[0].pk]
            )

        report = TaskTracker.objects.first()
        self.assertFalse(report.completed)
        self.assertEqual((report.total_to_process, report.total_processed), (1, 0))
        self.assertEqual(report.detail["events"][-1]["websites"][0]["total_failed"], 1)
