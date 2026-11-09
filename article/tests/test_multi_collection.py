"""
Artigo presente em mais de uma coleção: um Article por documento na
coleção (CollectionPidV2), com o mesmo pid_v3.

Ex.: Psicologia USP
- scl: acron=pusp, artigo S0103-65642009000300003
- psi: acron=psicousp, artigo S1678-51772009000300003
"""

from unittest.mock import DEFAULT, Mock, PropertyMock, patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from article.models import Article
from article.tests.utils import create_sps_pkg
from collection.models import Collection
from journal.models import Journal
from package.models import SPSPkg
from pid_provider.models import CollectionPidV2
from proc.models import JournalProc

User = get_user_model()

PID_V3 = "V3-PSICOUSP-0000000001"
SCL_V2 = "S0103-65642009000300003"
PSI_V2 = "S1678-51772009000300003"


class ArticleByCollectionTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="article-multicol")
        self.scl = Collection.objects.create(
            acron="scl", network_classification=["scielonetwork"], creator=self.user
        )
        self.psi = Collection.objects.create(
            acron="psi", network_classification=["thematic"], creator=self.user
        )
        self.journal = Journal.objects.create(creator=self.user)
        # psi é criada antes de scl para verificar que a principal vem primeiro
        for collection, acron, pid in (
            (self.psi, "psicousp", "1678-5177"),
            (self.scl, "pusp", "0103-6564"),
        ):
            JournalProc.objects.create(
                journal=self.journal,
                collection=collection,
                acron=acron,
                pid=pid,
                creator=self.user,
            )

        # create_or_update: somente a identificação do Article por coleção
        patcher = patch.multiple(
            Article,
            add_journal=DEFAULT,
            add_issue=DEFAULT,
            add_pages=DEFAULT,
            add_article_publication_date=DEFAULT,
            add_data_availability_status=DEFAULT,
            add_sections=DEFAULT,
            add_position_in_table_of_contents=DEFAULT,
            add_article_titles=DEFAULT,
            add_doi_with_lang=DEFAULT,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        xml_with_pre = Mock()
        xml_with_pre.xmltree.find.return_value.get.return_value = "research-article"
        patcher = patch.object(
            SPSPkg, "xml_with_pre", new_callable=PropertyMock, return_value=xml_with_pre
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def create_sps_pkg(self, collection, pid_v2=SCL_V2, name="pkg"):
        # SPSPkg do documento (PidProviderXML) na coleção (CollectionPidV2)
        return create_sps_pkg(
            self.user, name, pid_v3=PID_V3, collection=collection, pid_v2=pid_v2
        )

    def create_article(self, collection, pid_v2=SCL_V2, name="pkg"):
        sps_pkg = self.create_sps_pkg(collection, pid_v2, name)
        article = Article(creator=self.user, pid_v3=PID_V3)
        article.set_collection_pid_v2(sps_pkg.collection_pid_v2)
        article.save()
        return article

    def create_or_update(self, sps_pkg, collection=None):
        return Article.create_or_update(
            self.user, sps_pkg, journal=self.journal, collection=collection
        )


class ArticleUniqueByCollectionTest(ArticleByCollectionTestBase):
    def test_same_pid_v3_in_different_collections(self):
        self.create_article(self.scl, SCL_V2, "scl")
        self.create_article(self.psi, PSI_V2, "psi")
        self.assertEqual(Article.objects.filter(pid_v3=PID_V3).count(), 2)

    def test_one_article_per_document_in_the_collection(self):
        article = self.create_article(self.scl)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Article.objects.create(
                creator=self.user,
                pid_v3=PID_V3,
                collection_pid_v2=article.collection_pid_v2,
            )

    def test_pid_v3_is_unique_without_collection(self):
        Article.objects.create(creator=self.user, pid_v3=PID_V3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Article.objects.create(creator=self.user, pid_v3=PID_V3)

    def test_data_of_the_document_in_the_collection(self):
        article = self.create_article(self.psi, PSI_V2, "1678-5177-psicousp")

        article = Article.objects.get(pk=article.pk)
        self.assertEqual(article.collection, self.psi)
        self.assertEqual(article.pid_v2, PSI_V2)
        self.assertEqual(article.pp_xml.v3, PID_V3)
        self.assertEqual(article.sps_pkg.sps_pkg_name, "1678-5177-psicousp")
        self.assertEqual(article.sps_pkg.pid_v3, PID_V3)
        self.assertEqual(article.sps_pkg.pid_v2, PSI_V2)
        self.assertEqual(article.sps_pkg.collection, self.psi)

    def test_article_without_collection_pid_v2(self):
        article = Article.objects.create(creator=self.user, pid_v3=PID_V3)
        self.assertIsNone(article.collection)
        self.assertIsNone(article.pid_v2)
        self.assertIsNone(article.pp_xml)
        self.assertIsNone(article.sps_pkg)

    def test_get_by_pid_v3_returns_the_article_of_the_main_collection(self):
        scl = self.create_article(self.scl, SCL_V2, "scl")
        self.create_article(self.psi, PSI_V2, "psi")
        self.assertEqual(Article.get_by_pid_v3(PID_V3), scl)
        with self.assertRaises(Article.DoesNotExist):
            Article.get_by_pid_v3("not-registered")

    def test_get_by_collection_and_pid_v2(self):
        psi = self.create_article(self.psi, PSI_V2, "psi")
        self.create_article(self.scl, SCL_V2, "scl")
        self.assertEqual(Article.get(pid_v3=PID_V3, collection=self.psi), psi)
        self.assertEqual(Article.get(pid_v2=PSI_V2, collection=self.psi), psi)
        with self.assertRaises(Article.DoesNotExist):
            Article.get(pid_v2=PSI_V2, collection=self.scl)
        self.assertEqual(Article.get(sps_pkg_name="psi", collection=self.psi), psi)
        self.assertEqual(Article.get_by_sps_pkg_name("psi"), psi)
        # sem a coleção
        with self.assertRaises(ValueError):
            Article.get(pid_v3=PID_V3)

    def test_get_by_sps_pkg_name_uses_the_name_of_the_package(self):
        # CollectionPidV2.sps_pkg_name com o pid v3 (dado legado)
        scl = self.create_article(self.scl, SCL_V2, "0103-6564-pusp-20-03-00003")
        psi = self.create_article(self.psi, PSI_V2, "1678-5177-psicousp-20-03-00003")
        from pid_provider.models import CollectionPidV2

        CollectionPidV2.objects.filter(pid_provider_xml__v3=PID_V3).update(
            sps_pkg_name=PID_V3
        )
        self.assertEqual(
            Article.get(sps_pkg_name="0103-6564-pusp-20-03-00003", collection=self.scl),
            scl,
        )
        self.assertEqual(
            Article.get_by_sps_pkg_name("1678-5177-psicousp-20-03-00003"), psi
        )
        with self.assertRaises(Article.DoesNotExist):
            Article.get_by_sps_pkg_name(PID_V3)

    def test_filter_by_journal_acron_of_the_collection(self):
        scl = self.create_article(self.scl, SCL_V2, "scl")
        psi = self.create_article(self.psi, PSI_V2, "psi")
        Article.objects.filter(pk__in=[scl.pk, psi.pk]).update(journal=self.journal)
        # acrônimos diferentes nas coleções: journal_acron vazio
        self.assertIsNone(self.journal.update_journal_acron())

        qs = Article.objects.all()
        self.assertEqual(list(Article.filter_by_journal_acron(qs, "pusp")), [scl])
        self.assertEqual(list(Article.filter_by_journal_acron(qs, "psicousp")), [psi])
        self.assertEqual(list(Article.filter_by_journal_acron(qs, "other")), [])


class ArticleCreateOrUpdateByCollectionTest(ArticleByCollectionTestBase):
    def test_package_of_each_collection_creates_one_article_per_collection(self):
        scl_pkg = self.create_sps_pkg(self.scl, SCL_V2, "0103-6564-pusp")
        psi_pkg = self.create_sps_pkg(self.psi, PSI_V2, "1678-5177-psicousp")

        scl = self.create_or_update(scl_pkg)
        psi = self.create_or_update(psi_pkg, self.psi)

        self.assertNotEqual(scl.pk, psi.pk)
        self.assertEqual(
            (scl.collection, scl.sps_pkg, scl.pid_v2), (self.scl, scl_pkg, SCL_V2)
        )
        self.assertEqual(
            (psi.collection, psi.sps_pkg, psi.pid_v2), (self.psi, psi_pkg, PSI_V2)
        )

    def test_updates_the_article_of_the_collection(self):
        sps_pkg = self.create_sps_pkg(self.scl)
        first = self.create_or_update(sps_pkg)
        second = self.create_or_update(sps_pkg)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Article.objects.count(), 1)

    def test_package_of_other_collection_is_rejected(self):
        with self.assertRaises(ValueError):
            self.create_or_update(self.create_sps_pkg(self.scl), self.psi)

    def test_package_without_collection_pid_v2_is_rejected_for_the_collection(self):
        sps_pkg = SPSPkg.objects.create(creator=self.user, sps_pkg_name="pkg")
        with self.assertRaises(ValueError):
            self.create_or_update(sps_pkg, self.scl)

    def test_package_without_collection_creates_article_without_collection(self):
        # ex.: ingresso (upload), sem coleção
        sps_pkg = SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="pkg", pid_v3=PID_V3, pid_v2=SCL_V2
        )
        article = self.create_or_update(sps_pkg)
        self.assertIsNone(article.collection_pid_v2)
        self.assertEqual(article.sps_pkg, sps_pkg)
        self.assertEqual(article.pid_v2, SCL_V2)

    def test_article_without_collection_is_adopted_by_the_collection(self):
        # artigo anterior à separação por coleção
        legacy = Article.objects.create(creator=self.user, pid_v3=PID_V3)
        psi_pkg = self.create_sps_pkg(self.psi, PSI_V2, "psi")

        psi = self.create_or_update(psi_pkg)
        scl = self.create_or_update(self.create_sps_pkg(self.scl, SCL_V2, "scl"))

        self.assertEqual(psi.pk, legacy.pk)
        self.assertEqual(psi.collection, self.psi)
        self.assertNotEqual(scl.pk, legacy.pk)
        self.assertEqual(Article.objects.filter(pid_v3=PID_V3).count(), 2)

    def test_exclude_invalid_records_keeps_articles_of_each_collection(self):
        self.create_or_update(self.create_sps_pkg(self.scl, SCL_V2, "scl"))
        self.create_or_update(self.create_sps_pkg(self.psi, PSI_V2, "psi"))

        result = Article._exclude_invalid_records(self.user, None)

        self.assertEqual(result["duplicated_items"], [])
        self.assertEqual(Article.objects.filter(pid_v3=PID_V3).count(), 2)


class ArticleCompleteCollectionPidV2Test(ArticleByCollectionTestBase):
    """
    Article e SPSPkg anteriores à separação por coleção (sem
    collection_pid_v2) são vinculados ao documento na coleção ao serem
    obtidos ou pela tarefa em lotes, somente se não houver ambiguidade
    """

    def setUp(self):
        super().setUp()
        from pid_provider.models import PidProviderXML

        self.ppx = PidProviderXML.objects.create(creator=self.user, v3=PID_V3)

    def legacy(self, *collections, name="legacy", pid_v3=PID_V3):
        from pid_provider.models import PidProviderXML
        from proc.models import ArticleProc

        ppx = PidProviderXML.objects.get_or_create(
            v3=pid_v3, defaults={"creator": self.user}
        )[0]

        sps_pkg = SPSPkg.objects.create(
            creator=self.user,
            sps_pkg_name=name,
            ppx=ppx,
            pid_v3=pid_v3,
            pid_v2=SCL_V2,
        )
        for collection in collections:
            ArticleProc.objects.create(
                creator=self.user, collection=collection, sps_pkg=sps_pkg, pid=SCL_V2
            )
        article = Article.objects.create(
            creator=self.user,
            pid_v3=pid_v3,
            pid_v2=SCL_V2,
            pp_xml=ppx,
            sps_pkg=sps_pkg,
            journal=self.journal,
        )
        return article, sps_pkg

    def test_links_article_and_its_package(self):
        article, sps_pkg = self.legacy(self.scl)

        self.assertEqual(article.complete_collection_pid_v2(self.user), "linked")

        article.refresh_from_db()
        sps_pkg.refresh_from_db()
        self.assertEqual(article.collection, self.scl)
        self.assertEqual(article.collection_pid_v2, sps_pkg.collection_pid_v2)
        self.assertEqual(article.collection_pid_v2.sps_pkg, sps_pkg)
        self.assertEqual(article.collection_pid_v2.article, article)
        self.assertEqual(article.collection_pid_v2.journal_acron, "pusp")
        self.assertEqual(article.pid_v2, SCL_V2)

    def test_get_does_not_link_on_read(self):
        article, sps_pkg = self.legacy(self.scl)

        self.assertEqual(Article.get_by_pid_v3(PID_V3), article)
        self.assertEqual(Article.get(sps_pkg=sps_pkg), article)
        self.assertEqual(Article.get(pid_v3=PID_V3, collection=self.scl), article)
        article.refresh_from_db()
        sps_pkg.refresh_from_db()
        self.assertIsNone(article.collection_pid_v2)
        self.assertIsNone(sps_pkg.collection_pid_v2)

    def test_create_or_update_links(self):
        article, sps_pkg = self.legacy(self.scl)

        updated = Article.create_or_update(self.user, sps_pkg)

        self.assertEqual(updated.id, article.id)
        self.assertEqual(updated.collection, self.scl)

    def test_does_not_link_article_whose_package_is_of_more_than_one_collection(self):
        article, sps_pkg = self.legacy(self.scl, self.psi)

        self.assertEqual(
            article.complete_collection_pid_v2(self.user), "no_collection"
        )
        article.refresh_from_db()
        self.assertIsNone(article.collection_pid_v2)

    def test_get_returns_unlinked_article_without_linking(self):
        article, sps_pkg = self.legacy(self.scl)

        self.assertEqual(Article.get(pid_v3=PID_V3, collection=self.scl), article)
        article.refresh_from_db()
        self.assertIsNone(article.collection_pid_v2)

    def test_get_does_not_return_the_linked_article_of_another_collection(self):
        article, sps_pkg = self.legacy(self.scl)
        # vínculo completado pela migração / tarefa
        article.complete_collection_pid_v2(self.user)

        self.assertEqual(Article.get(pid_v3=PID_V3, collection=self.scl), article)
        with self.assertRaises(Article.DoesNotExist):
            Article.get(pid_v3=PID_V3, collection=self.psi)

    def test_get_returns_ambiguous_article(self):
        # sem vínculo possível: mantém o comportamento anterior
        article, sps_pkg = self.legacy(self.scl, self.psi)
        self.assertEqual(Article.get(pid_v3=PID_V3, collection=self.psi), article)

    def test_get_by_pid_v2_uses_the_field_of_the_article(self):
        article, sps_pkg = self.legacy(self.scl)
        self.assertEqual(Article.get(pid_v2=SCL_V2, collection=self.scl), article)

    def test_create_or_update_does_not_adopt_the_article_of_another_collection(self):
        legacy, legacy_pkg = self.legacy(self.scl)
        psi_pkg = create_sps_pkg(
            self.user, "psi", pid_v3=PID_V3, collection=self.psi, pid_v2=PSI_V2
        )

        psi = self.create_or_update(psi_pkg, self.psi)

        self.assertNotEqual(psi.pk, legacy.pk)
        self.assertEqual(psi.collection, self.psi)
        legacy.refresh_from_db()
        self.assertEqual(legacy.collection, self.scl)
        self.assertEqual(legacy.sps_pkg, legacy_pkg)

    def test_create_or_update_links_the_package_of_the_collection(self):
        legacy, legacy_pkg = self.legacy(self.scl)

        article = self.create_or_update(legacy_pkg, self.scl)

        self.assertEqual(article.pk, legacy.pk)
        legacy_pkg.refresh_from_db()
        self.assertEqual(article.collection_pid_v2, legacy_pkg.collection_pid_v2)
        self.assertEqual(article.collection, self.scl)

    def test_batch(self):
        article, sps_pkg = self.legacy(self.scl)
        ambiguous, ambiguous_pkg = self.legacy(
            self.scl, self.psi, name="other", pid_v3="OTHER"
        )

        stats, last_id, done = Article.complete_collection_pid_v2_batch(
            self.user, last_id=0, batch_size=10
        )

        self.assertEqual(stats, {"linked": 1, "no_collection": 1})
        self.assertEqual(last_id, ambiguous.id)
        self.assertTrue(done)


class CompleteCollectionPidV2MigrationTest(ArticleCompleteCollectionPidV2Test):
    """
    A mesma função vincula na migração (modelos históricos) e na tarefa;
    o que fica pendente na migração é continuado pela tarefa
    """

    def historical_apps(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        return executor.loader.project_state(
            ("article", "0014_complete_collection_pid_v2")
        ).apps

    def migration(self):
        import importlib

        return importlib.import_module(
            "article.migrations.0014_complete_collection_pid_v2"
        )

    def test_complete_links_sps_pkg_and_article_with_historical_models(self):
        from package import collection_pid_v2_completion as completion

        article, sps_pkg = self.legacy(self.scl)
        ambiguous, _ = self.legacy(self.scl, self.psi, name="other", pid_v3="OTHER")

        result = completion.complete(self.historical_apps(), batch_size=1)

        self.assertTrue(result["done"])
        self.assertEqual(result["stats"]["SPSPkg"], {"linked": 1, "no_collection": 1})
        self.assertEqual(result["stats"]["Article"], {"linked": 1, "no_collection": 1})
        article.refresh_from_db()
        sps_pkg.refresh_from_db()
        self.assertEqual(article.collection, self.scl)
        self.assertEqual(article.collection_pid_v2, sps_pkg.collection_pid_v2)
        self.assertEqual(article.collection_pid_v2.journal_acron, "pusp")
        self.assertEqual(sps_pkg.collection_pid_v2.sps_pkg_name, "legacy")
        self.assertEqual(
            completion.count_unlinked(self.historical_apps()),
            {"SPSPkg": 1, "Article": 1},
        )

    def test_complete_keeps_the_legacy_fields(self):
        from package import collection_pid_v2_completion as completion
        from pid_provider.models import XMLVersion

        article, sps_pkg = self.legacy(self.scl)
        ppx = sps_pkg.ppx
        ppx.v2 = "S0000-legacy"
        ppx.current_version = XMLVersion.objects.create(
            creator=self.user, pid_provider_xml=ppx, finger_print="legacy"
        )
        ppx.save()
        # documento na coleção já registrado com outro pid v2
        cpv2 = CollectionPidV2.objects.create(
            creator=self.user,
            pid_provider_xml=ppx,
            collection=self.scl,
            pid_v2="S0103-65642009000399999",
        )
        Article.objects.filter(id=article.id).update(pp_xml=None)

        completion.complete(self.historical_apps())

        ppx.refresh_from_db()
        sps_pkg.refresh_from_db()
        article.refresh_from_db()
        # PidProviderXML não é alterado
        self.assertEqual(ppx.v2, "S0000-legacy")
        self.assertEqual(ppx.current_version.finger_print, "legacy")
        # SPSPkg e Article: vinculados, legado mantido, vazio completado
        self.assertEqual(sps_pkg.collection_pid_v2, cpv2)
        self.assertEqual(article.collection_pid_v2, cpv2)
        self.assertEqual(sps_pkg.pid_v2, SCL_V2)
        self.assertEqual(article.pid_v2, SCL_V2)
        self.assertEqual(article.pp_xml, ppx)
        self.assertEqual(sps_pkg.get_pid_v2(), "S0103-65642009000399999")
        self.assertEqual(article.get_pid_v2(), "S0103-65642009000399999")

    def test_complete_stops_at_max_seconds_and_returns_the_cursor(self):
        from package import collection_pid_v2_completion as completion

        first, first_pkg = self.legacy(self.scl, name="first", pid_v3="FIRST")
        self.legacy(self.scl, name="second", pid_v3="SECOND")

        result = completion.complete(self.historical_apps(), batch_size=1, max_seconds=0)

        self.assertFalse(result["done"])
        self.assertEqual(result["model_name"], "SPSPkg")
        self.assertEqual(result["last_id"], first_pkg.id)

    @patch("article.tasks.task_complete_collection_pid_v2.apply_async")
    def test_task_continues_what_the_migration_left_pending(self, mock_apply_async):
        from article import tasks

        article, sps_pkg = self.legacy(self.scl, name="first", pid_v3="FIRST")
        article2, sps_pkg2 = self.legacy(self.scl, name="second", pid_v3="SECOND")
        with patch.dict(
            "os.environ", {"COLLECTION_PID_V2_MIGRATION_MAX_SECONDS": "0"}
        ):
            self.migration().complete_collection_pid_v2(self.historical_apps(), None)
        sps_pkg.refresh_from_db()
        self.assertIsNone(sps_pkg.collection_pid_v2)

        for model_name in ("SPSPkg", "Article"):
            result = tasks.task_complete_collection_pid_v2(
                user_id=self.user.id, model_name=model_name, batch_size=10
            )
        self.assertEqual(result["unlinked"], {"SPSPkg": 0, "Article": 0})
        for obj in (article, article2, sps_pkg, sps_pkg2):
            obj.refresh_from_db()
            self.assertEqual(obj.collection_pid_v2.collection, self.scl)

    def test_migration_does_not_fail_on_error(self):
        self.legacy(self.scl)
        with patch(
            "package.collection_pid_v2_completion.complete",
            side_effect=RuntimeError("boom"),
        ):
            self.migration().complete_collection_pid_v2(self.historical_apps(), None)

    def test_migration_links_without_time_limit(self):
        article, sps_pkg = self.legacy(self.scl)
        with patch.dict(
            "os.environ", {"COLLECTION_PID_V2_MIGRATION_MAX_SECONDS": "none"}
        ):
            self.migration().complete_collection_pid_v2(self.historical_apps(), None)
        article.refresh_from_db()
        self.assertEqual(article.collection, self.scl)


class TaskCompleteCollectionPidV2Test(ArticleByCollectionTestBase):
    @patch("article.tasks.task_complete_collection_pid_v2.apply_async")
    def test_schedules_the_next_batch(self, mock_apply_async):
        from article import tasks

        with patch.object(
            SPSPkg, "complete_collection_pid_v2_batch", return_value=({}, 7, False)
        ):
            tasks.task_complete_collection_pid_v2(
                user_id=self.user.id, batch_size=5, countdown=10
            )

        kwargs = mock_apply_async.call_args.kwargs
        self.assertEqual(kwargs["countdown"], 10)
        self.assertEqual(kwargs["kwargs"]["model_name"], "SPSPkg")
        self.assertEqual(kwargs["kwargs"]["last_id"], 7)

    @patch("article.tasks.task_complete_collection_pid_v2.apply_async")
    def test_continues_with_article_after_sps_pkg(self, mock_apply_async):
        from article import tasks

        with patch.object(
            SPSPkg, "complete_collection_pid_v2_batch", return_value=({}, 7, True)
        ):
            tasks.task_complete_collection_pid_v2(user_id=self.user.id)

        kwargs = mock_apply_async.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["model_name"], "Article")
        self.assertEqual(kwargs["last_id"], 0)

    @patch("article.tasks.task_complete_collection_pid_v2.apply_async")
    def test_stops_after_article(self, mock_apply_async):
        from article import tasks

        with patch.object(
            Article, "complete_collection_pid_v2_batch", return_value=({}, 7, True)
        ):
            tasks.task_complete_collection_pid_v2(
                user_id=self.user.id, model_name="Article"
            )

        mock_apply_async.assert_not_called()

    @patch("article.tasks.task_complete_collection_pid_v2.apply_async")
    def test_stops_after_max_batches(self, mock_apply_async):
        from article import tasks

        with patch.object(
            SPSPkg, "complete_collection_pid_v2_batch", return_value=({}, 7, False)
        ):
            tasks.task_complete_collection_pid_v2(user_id=self.user.id, max_batches=1)

        mock_apply_async.assert_not_called()
