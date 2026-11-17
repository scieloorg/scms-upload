"""
Testes da decisão de migrar e de publicar artigos (ArticleProc) e da
preservação do migration_status definido no registro dos dados do site
clássico.
"""

from unittest.mock import MagicMock, patch

from django.db.models import Q
from django.test import SimpleTestCase

from proc.models import ArticleProc
from tracker import choices as tracker_choices

TODO = tracker_choices.PROGRESS_STATUS_TODO
REPROC = tracker_choices.PROGRESS_STATUS_REPROC
DONE = tracker_choices.PROGRESS_STATUS_DONE
PENDING = tracker_choices.PROGRESS_STATUS_PENDING
BLOCKED = tracker_choices.PROGRESS_STATUS_BLOCKED
IGNORED = tracker_choices.PROGRESS_STATUS_IGNORED
DOING = tracker_choices.PROGRESS_STATUS_DOING

ROUTINE = [REPROC, TODO]


def article_proc(migration_status=DONE, xml_status=DONE, sps_pkg_status=DONE):
    return ArticleProc(
        migration_status=migration_status,
        xml_status=xml_status,
        sps_pkg_status=sps_pkg_status,
    )


class NeedsMigrationTest(SimpleTestCase):
    def test_migration_status_in_status(self):
        for status in (TODO, REPROC):
            with self.subTest(status=status):
                self.assertTrue(article_proc(status).needs_migration(ROUTINE))

    def test_migration_step_in_status(self):
        self.assertTrue(
            article_proc(DONE, xml_status=REPROC).needs_migration(ROUTINE)
        )
        self.assertTrue(
            article_proc(DONE, sps_pkg_status=TODO).needs_migration(ROUTINE)
        )

    def test_migrated_article_is_not_migrated_again(self):
        self.assertFalse(article_proc(DONE).needs_migration(ROUTINE))

    def test_items_waiting_for_user_are_not_migrated_by_routine(self):
        for status in (IGNORED, PENDING, BLOCKED):
            with self.subTest(status=status):
                item = article_proc(status, xml_status=TODO, sps_pkg_status=TODO)
                self.assertFalse(item.needs_migration(ROUTINE))

    def test_explicit_status_migrates_items_waiting_for_user(self):
        item = article_proc(BLOCKED, xml_status=TODO)
        self.assertTrue(item.needs_migration([BLOCKED]))

    def test_blocked_step_with_explicit_status(self):
        item = article_proc(TODO, xml_status=BLOCKED)
        self.assertTrue(item.needs_migration([BLOCKED]))


    def test_failed_step_is_not_retried_by_routine(self):
        # get_xml falhou: migration_status continua TODO
        self.assertFalse(
            article_proc(TODO, xml_status=BLOCKED).needs_migration(ROUTINE)
        )
        self.assertFalse(
            article_proc(TODO, xml_status=DONE, sps_pkg_status=BLOCKED)
            .needs_migration(ROUTINE)
        )

    def test_failed_step_is_retried_with_explicit_status(self):
        item = article_proc(TODO, xml_status=DONE, sps_pkg_status=BLOCKED)
        self.assertTrue(item.needs_migration([BLOCKED]))


    def test_any_status_is_accepted(self):
        # DONE: refaz os já migrados
        self.assertTrue(article_proc(DONE).needs_migration([DONE]))
        self.assertTrue(article_proc(IGNORED).needs_migration([IGNORED]))
        # fase interrompida (worker encerrado)
        self.assertTrue(
            article_proc(TODO, xml_status=DONE, sps_pkg_status=DOING)
            .needs_migration([DOING])
        )

    def test_status_of_other_step_does_not_select(self):
        # retoma da primeira fase não concluída; as seguintes dependem dela
        item = article_proc(TODO, xml_status=BLOCKED, sps_pkg_status=TODO)
        self.assertFalse(item.needs_migration(ROUTINE))
        self.assertFalse(article_proc(DONE).needs_migration([BLOCKED]))

class CurrentMigrationStepStatusTest(SimpleTestCase):
    def test_first_step_not_done(self):
        self.assertEqual(
            article_proc(TODO, BLOCKED, TODO).current_migration_step_status,
            BLOCKED,
        )
        self.assertEqual(
            article_proc(TODO, DONE, REPROC).current_migration_step_status,
            REPROC,
        )
        self.assertEqual(
            article_proc(BLOCKED, DONE, DONE).current_migration_step_status,
            BLOCKED,
        )

    def test_all_steps_done(self):
        self.assertIsNone(article_proc(DONE).current_migration_step_status)


class MigrateArticleResumeTest(SimpleTestCase):
    def _migrate(self, item, force_update=False):
        with patch.object(ArticleProc, "save"), patch.object(
            ArticleProc, "get_xml", return_value=True
        ) as get_xml, patch.object(
            ArticleProc, "generate_sps_package", return_value=True
        ) as generate_sps_package, patch.object(
            ArticleProc, "create_or_update_item", return_value="article"
        ) as create_or_update_item, patch.object(
            ArticleProc,
            "get_publication_status",
            side_effect=lambda purpose, status: status,
        ):
            article = item.migrate_article(None, force_update)
        return article, get_xml, generate_sps_package, create_or_update_item

    def test_resumes_from_sps_pkg_step(self):
        item = article_proc(TODO, xml_status=DONE, sps_pkg_status=BLOCKED)
        article, get_xml, generate_sps_package, create_or_update_item = (
            self._migrate(item)
        )
        self.assertEqual(article, "article")
        get_xml.assert_not_called()
        generate_sps_package.assert_called_once()
        create_or_update_item.assert_called_once()

    def test_resumes_from_article_step(self):
        item = article_proc(BLOCKED, xml_status=DONE, sps_pkg_status=DONE)
        _, get_xml, generate_sps_package, create_or_update_item = self._migrate(
            item
        )
        get_xml.assert_not_called()
        generate_sps_package.assert_not_called()
        create_or_update_item.assert_called_once()

    def test_runs_all_steps_from_xml(self):
        item = article_proc(TODO, xml_status=TODO, sps_pkg_status=TODO)
        _, get_xml, generate_sps_package, create_or_update_item = self._migrate(
            item
        )
        get_xml.assert_called_once()
        generate_sps_package.assert_called_once()
        create_or_update_item.assert_called_once()

    def test_force_update_runs_all_steps(self):
        item = article_proc(DONE)
        _, get_xml, generate_sps_package, _ = self._migrate(item, force_update=True)
        get_xml.assert_called_once()
        generate_sps_package.assert_called_once()

    def test_all_steps_done_redoes_all_steps(self):
        # artigo selecionado por DONE
        item = article_proc(DONE)
        _, get_xml, generate_sps_package, create_or_update_item = self._migrate(
            item
        )
        get_xml.assert_called_once()
        generate_sps_package.assert_called_once()
        create_or_update_item.assert_called_once()

    def test_stops_on_failed_step(self):
        item = article_proc(TODO, xml_status=TODO, sps_pkg_status=TODO)
        with patch.object(ArticleProc, "save"), patch.object(
            ArticleProc, "get_xml", return_value=False
        ), patch.object(
            ArticleProc, "generate_sps_package"
        ) as generate_sps_package:
            self.assertIsNone(item.migrate_article(None, False))
        generate_sps_package.assert_not_called()

class SelectItemsToPublishTest(SimpleTestCase):
    def _select(self, website_kind, status, migrated_ids=None):
        articles = MagicMock()
        filtered = articles.filter.return_value
        filtered.filter.return_value = filtered
        filtered.values_list.return_value = [1, 2]
        ids = ArticleProc.select_items_to_publish(
            articles, website_kind, status, migrated_ids=migrated_ids
        )
        return articles, filtered, ids

    def test_qa_selects_migrated_with_pid_v3_and_status(self):
        articles, filtered, ids = self._select("QA", ROUTINE)

        self.assertEqual(ids, [1, 2])
        args, kwargs = articles.filter.call_args
        self.assertEqual(args[0], Q(qa_ws_status__in=ROUTINE))
        self.assertEqual(kwargs["migration_status"], DONE)
        self.assertIs(
            kwargs["sps_pkg__collection_pid_v2__pid_provider_xml__v3__isnull"], False
        )
        # no QA, não depende de publicação prévia
        filtered.filter.assert_not_called()

    def test_public_requires_qa_done_or_ignored(self):
        articles, filtered, _ = self._select("PUBLIC", ROUTINE)

        args, _ = articles.filter.call_args
        self.assertEqual(args[0], Q(public_ws_status__in=ROUTINE))
        filtered.filter.assert_called_once_with(qa_ws_status__in=(DONE, IGNORED))

    def test_migrated_ids_are_published_if_pending(self):
        articles, _, _ = self._select("QA", [BLOCKED], migrated_ids=[7])

        args, _ = articles.filter.call_args
        expected = Q(qa_ws_status__in=[BLOCKED]) | Q(
            id__in=[7],
            qa_ws_status__in=ArticleProc.get_status_to_publish(
                [BLOCKED], migrated=True
            ),
        )
        self.assertEqual(args[0], expected)


@patch.object(ArticleProc, "save")
@patch.object(
    ArticleProc, "get_publication_status", side_effect=lambda purpose, status: status
)
class UpdateTest(SimpleTestCase):
    def _update(self, current_status, **kwargs):
        item = ArticleProc(
            migration_status=current_status,
            xml_status=DONE,
            sps_pkg_status=DONE,
            qa_ws_status=DONE,
            public_ws_status=DONE,
        )
        item.update(pkg_name="pkg", **kwargs)
        return item

    def assert_steps(self, item, status):
        self.assertEqual(
            (
                item.xml_status,
                item.sps_pkg_status,
                item.qa_ws_status,
                item.public_ws_status,
            ),
            (status, status, status, status),
        )

    def test_item_to_migrate_resets_next_steps(self, *mocks):
        for status in (TODO, REPROC):
            with self.subTest(status=status):
                item = self._update(status)
                self.assertEqual(item.migration_status, status)
                self.assert_steps(item, TODO)

    def test_keeps_migration_status_set_on_registration(self, *mocks):
        for status in (DONE, PENDING, BLOCKED, IGNORED):
            with self.subTest(status=status):
                item = self._update(status)
                self.assertEqual(item.migration_status, status)
                self.assert_steps(item, DONE)
                self.assertEqual(item.pkg_name, "pkg")

    def test_explicit_migration_status(self, *mocks):
        item = self._update(DONE, migration_status=REPROC)
        self.assertEqual(item.migration_status, REPROC)
        self.assert_steps(item, TODO)
