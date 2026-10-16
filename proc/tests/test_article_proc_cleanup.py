from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from issue.models import Issue
from package.models import SPSPkg
from proc.models import ArticleProc, IssueProc
from tracker import choices


class ArticleProcCleanupTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="cleanup-review")
        self.collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )
        self.issue = Issue.objects.create(creator=self.user)
        self.issue_proc = IssueProc.objects.create(
            collection=self.collection, issue=self.issue, creator=self.user
        )

    def create_record(self, **fields):
        params = dict.fromkeys(
            ("migration_status", "xml_status", "sps_pkg_status"),
            choices.PROGRESS_STATUS_DONE,
        )
        params.update(
            collection=self.collection, issue_proc=self.issue_proc, creator=self.user
        )
        params.update(fields)
        return ArticleProc.objects.create(**params)

    def test_cleanup_preserves_only_pending_records_and_other_issues(self):
        pending = [
            self.create_record(**{field: status}).pk
            for field in ("migration_status", "xml_status", "sps_pkg_status")
            for status in choices.PROGRESS_STATUS_REGULAR_TODO
        ]
        other_issue = Issue.objects.create(creator=self.user)
        other_proc = IssueProc.objects.create(
            collection=self.collection, issue=other_issue, creator=self.user
        )
        preserved = pending + [self.create_record(issue_proc=other_proc).pk]
        for status in (
            choices.PROGRESS_STATUS_BLOCKED,
            choices.PROGRESS_STATUS_PENDING,
            choices.PROGRESS_STATUS_DONE,
        ):
            self.create_record(
                migration_status=status, xml_status=status, sps_pkg_status=status
            )

        with patch.object(SPSPkg, "complete_pid_v2"):
            response = ArticleProc.exclude_invalid_items(self.user, self.issue, delete=True)

        self.assertNotIn("error", response)
        self.assertCountEqual(
            ArticleProc.objects.values_list("pk", flat=True), preserved
        )

    def test_pending_status_does_not_protect_package_with_incorrect_pid(self):
        valid_package = SPSPkg.objects.create(creator=self.user)
        invalid_package = SPSPkg.objects.create(creator=self.user)
        valid = self.create_record(sps_pkg=valid_package)
        self.create_record(
            sps_pkg=invalid_package, migration_status=choices.PROGRESS_STATUS_TODO
        )

        with patch.object(SPSPkg, "complete_pid_v2"), patch.object(
            ArticleProc,
            "get_sps_pkg_ids_which_pid_v2_is_incorrect",
            return_value={invalid_package.pk},
        ):
            response = ArticleProc.exclude_invalid_items(self.user, self.issue, delete=True)

        self.assertNotIn("error", response)
        self.assertCountEqual(
            ArticleProc.objects.values_list("pk", flat=True), [valid.pk]
        )
