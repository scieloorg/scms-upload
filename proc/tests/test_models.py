from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from proc.models import ArticleProc, IssueProc
from tracker import choices as tracker_choices

User = get_user_model()


class ArticleProcExcludeInvalidRecordsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )
        self.issue_proc = IssueProc.objects.create(
            collection=self.collection,
            pid="0034-891020040002",
            creator=self.user,
            updated_by=self.user,
        )

    def create_article_proc(
        self, pid, migration_status, xml_status=None, sps_pkg_status=None
    ):
        return ArticleProc.objects.create(
            collection=self.collection,
            issue_proc=self.issue_proc,
            pid=pid,
            migration_status=migration_status,
            xml_status=xml_status or migration_status,
            sps_pkg_status=sps_pkg_status or migration_status,
            creator=self.user,
            updated_by=self.user,
        )

    def test_preserves_pending_without_sps_pkg(self):
        pending = [
            self.create_article_proc("A1", tracker_choices.PROGRESS_STATUS_TODO),
            self.create_article_proc("A2", tracker_choices.PROGRESS_STATUS_REPROC),
            self.create_article_proc(
                "A3",
                tracker_choices.PROGRESS_STATUS_DONE,
                tracker_choices.PROGRESS_STATUS_TODO,
            ),
        ]

        response = ArticleProc.exclude_invalid_records(
            self.user, self.issue_proc.id, True, True
        )

        self.assertEqual(response["total_deleted_items"], 0)
        self.assertEqual(
            ArticleProc.objects.filter(id__in=[item.id for item in pending]).count(), 3
        )

    def test_deletes_non_pending_without_sps_pkg(self):
        ids = [
            self.create_article_proc("B1", tracker_choices.PROGRESS_STATUS_BLOCKED).id,
            self.create_article_proc("B2", tracker_choices.PROGRESS_STATUS_PENDING).id,
            self.create_article_proc("B3", tracker_choices.PROGRESS_STATUS_DONE).id,
        ]

        ArticleProc.exclude_invalid_records(self.user, self.issue_proc.id, True, True)

        self.assertFalse(ArticleProc.objects.filter(id__in=ids).exists())
