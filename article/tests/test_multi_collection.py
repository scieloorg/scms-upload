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
        return Article.objects.create(
            creator=self.user,
            pid_v3=PID_V3,
            collection_pid_v2=sps_pkg.collection_pid_v2,
        )

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
        self.assertEqual(Article.get(pid_v2=PSI_V2), psi)
        self.assertEqual(Article.get(sps_pkg_name="psi"), psi)


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

    def test_package_without_collection_pid_v2_is_rejected(self):
        sps_pkg = SPSPkg.objects.create(creator=self.user, sps_pkg_name="pkg")
        with self.assertRaises(ValueError):
            self.create_or_update(sps_pkg)

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
