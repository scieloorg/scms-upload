from unittest.mock import patch

from django.test import TestCase

from article import choices, tasks
from article.models import Article
from article.tests.data_availability_fixtures import ReportDataMixin, make_xmltree
from package.models import SPSPkg


class TaskUpdateDataAvailabilityStatusTest(ReportDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # tarefa só considera artigos com sps_pkg
        for i, article in enumerate(cls.articles):
            article.sps_pkg = SPSPkg.objects.create(
                creator=cls.user, sps_pkg_name=f"pkg-{i}"
            )
            article.save()
        cls.not_processed = cls.articles[3]

    def _ids(self, mock_subtask):
        ids = []
        for call in mock_subtask.apply_async.call_args_list:
            ids.extend(call.kwargs["kwargs"]["article_ids"])
        return ids

    @patch("article.tasks.task_update_data_availability_status_for_articles")
    def test_dispatches_only_not_processed(self, mock_subtask):
        total = tasks.task_update_data_availability_status()
        self.assertEqual(1, total)
        self.assertEqual([self.not_processed.pk], self._ids(mock_subtask))

    @patch("article.tasks.task_update_data_availability_status_for_articles")
    def test_force_update_dispatches_all(self, mock_subtask):
        total = tasks.task_update_data_availability_status(force_update=True)
        self.assertEqual(4, total)
        self.assertEqual(
            sorted(a.pk for a in self.articles), sorted(self._ids(mock_subtask))
        )
        kwargs = mock_subtask.apply_async.call_args.kwargs["kwargs"]
        self.assertTrue(kwargs["force_update"])

    @patch("article.tasks.task_update_data_availability_status_for_articles")
    def test_batches(self, mock_subtask):
        tasks.task_update_data_availability_status(force_update=True, batch_size=3)
        self.assertEqual(2, mock_subtask.apply_async.call_count)
        self.assertEqual(4, len(self._ids(mock_subtask)))

    @patch("article.tasks.task_update_data_availability_status_for_articles")
    def test_filter_collection(self, mock_subtask):
        total = tasks.task_update_data_availability_status(
            collection_acron="aaa", force_update=True
        )
        self.assertEqual(3, total)

    @patch("article.tasks.task_update_data_availability_status_for_articles")
    def test_filter_publication_year(self, mock_subtask):
        total = tasks.task_update_data_availability_status(
            publication_year="2023", force_update=True
        )
        self.assertEqual(2, total)

    @patch("article.tasks.task_update_data_availability_status_for_articles")
    def test_ignores_article_without_sps_pkg(self, mock_subtask):
        Article.objects.filter(pk=self.not_processed.pk).update(sps_pkg=None)
        self.assertEqual(0, tasks.task_update_data_availability_status())
        mock_subtask.apply_async.assert_not_called()

    @patch("article.tasks.UnexpectedEvent.create")
    @patch("article.tasks._filter_articles", side_effect=Exception("boom"))
    def test_registers_unexpected_event(self, mock_filter, mock_event):
        tasks.task_update_data_availability_status()
        mock_event.assert_called_once()


class TaskUpdateDataAvailabilityStatusForArticlesTest(ReportDataMixin, TestCase):
    @patch.object(SPSPkg, "xml_with_pre", create=True)
    def test_updates_given_articles(self, mock_xml_with_pre):
        article = self.articles[3]
        article.sps_pkg = SPSPkg.objects.create(creator=self.user, sps_pkg_name="pkg")
        article.save()
        mock_xml_with_pre.xmltree = make_xmltree(
            '<sec sec-type="data-availability" specific-use="data-not-available"/>'
        )

        updated = tasks.task_update_data_availability_status_for_articles(
            article_ids=[article.pk]
        )

        self.assertEqual(1, updated)
        article.refresh_from_db()
        self.assertEqual(choices.DAS_DATA_NOT_AVAILABLE, article.data_availability_status)

    @patch("article.tasks.UnexpectedEvent.create")
    @patch.object(Article, "update_data_availability_status", side_effect=Exception("boom"))
    def test_registers_unexpected_event(self, mock_update, mock_event):
        tasks.task_update_data_availability_status_for_articles(article_ids=[1])
        mock_event.assert_called_once()
