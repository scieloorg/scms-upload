import gzip
from unittest.mock import PropertyMock, call, patch

from article.models import Article, ArticleDOIWithLang
from collection.models import Collection, WebSiteConfiguration
from core.users.models import User
from core.utils.requester import NonRetryableError, RetryableError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from issue.models import Issue
from journal.models import Journal, JournalCollection, OfficialJournal
from migration.models import MigratedArticle
from proc.models import JournalProc

from .models import (ArticleAvailability, CollectionVerificationFile,
                     ScieloURLStatus)
from .tasks import (create_or_updated_migrated_article,
                    fetch_data_and_register_result,
                    initiate_article_availability_check,
                    process_article_availability,
                    process_file_to_check_migrated_articles,
                    retry_failed_scielo_urls)


class ArticleAvailabilityTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="user_test")
        self.collection_scl = Collection.objects.create(acron="scl", creator=self.user)
        self.collection_mex = Collection.objects.create(acron="mex", creator=self.user)
        self.web_site_configuration_mex = WebSiteConfiguration.objects.create(
            creator=self.user,
            collection=self.collection_mex,
            url="https://mocked-domain2.com",
            enabled=True,
            purpose="PUBLIC",
        )
        self.web_site_configuration_scl = WebSiteConfiguration.objects.create(
            creator=self.user,
            collection=self.collection_scl,
            url="https://mocked-domain.com",
            enabled=True,
            purpose="PUBLIC",
        )
        self.web_site_configuration_scl = WebSiteConfiguration.objects.create(
            creator=self.user,
            collection=self.collection_scl,
            url="https://qa-mocked-domain.com",
            enabled=True,
            purpose="QA",
        )
        self.official_journal = OfficialJournal.objects.create(
            issn_print="0000-0000",
            issn_electronic="XXXX-XXXX",
            creator=self.user,
        )
        self.journal = Journal.objects.create(
            official_journal=self.official_journal,
            journal_acron="abdc",
            creator=self.user,
        )
        self.journal_collection_scl = JournalCollection.objects.create(
            journal=self.journal,
            collection=self.collection_scl,
            creator=self.user,
        )
        self.journal_collection_mex = JournalCollection.objects.create(
            journal=self.journal,
            collection=self.collection_mex,
            creator=self.user,
        )
        self.journal_proc = JournalProc.objects.create(
            journal=self.journal,
            collection=self.collection_scl,
            acron="abdc",
            creator=self.user,
        )
        self.issue = Issue.objects.create(publication_year=2023, creator=self.user)
        self.article = Article.objects.create(
            journal=self.journal,
            issue=self.issue,
            pid_v3="test_pid_v3",
            pid_v2="test_pid_v2",
            creator=self.user,
        )
        self.doi_en = ArticleDOIWithLang.objects.create(
            doi_with_lang=self.article,
            doi="10.1016/j.iheduc.2015.08.004",
            lang="en",
            creator=self.user,
        )
        self.doi_pt = ArticleDOIWithLang.objects.create(
            doi_with_lang=self.article,
            doi="10.1016/j.iheduc.2015.08.004",
            lang="pt",
            creator=self.user,
        )

    def get_url(self, domain, journal_acron, pid_v2, pid_v3, lang):
        return [
            f"{domain}/scielo.php?script=sci_arttext&pid={pid_v2}&lang={lang}&nrm=iso",
            f"{domain}/j/{journal_acron}/a/{pid_v3}/?lang={lang}",
            f"{domain}/scielo.php?script=sci_arttext&pid={pid_v2}&format=pdf&lng={lang}&nrm=iso",
            f"{domain}/j/{journal_acron}/a/{pid_v3}/?format=pdf&lang={lang}",
        ]

    @patch("publication.tasks.Article.article_langs", new_callable=PropertyMock)
    @patch("publication.tasks.process_article_availability.apply_async")
    def test_initiate_article_availability_check(
        self,
        mock_process_apply_async,
        mock_property_article_langs,
    ):
        mock_property_article_langs.side_effect = ["pt", "es"]
        initiate_article_availability_check(
            user_id=1, username="user_test", collection_acron="scl", purpose="PUBLIC"
        )

        self.assertEqual(mock_process_apply_async.call_count, 2)

    @patch("publication.tasks.Article.article_langs", new_callable=PropertyMock)
    @patch("publication.tasks.process_article_availability.apply_async")
    def test_initiate_article_availability_check_with_params(
        self,
        mock_process_apply_async,
        mock_property_article_langs,
    ):
        mock_property_article_langs.side_effect = ["pt", "es"]
        initiate_article_availability_check(
            user_id=1,
            username="user_test",
            issn_print="0000-0000",
            issn_electronic="XXXX-XXXX",
            article_pid_v3="test_pid_v3",
            purpose="PUBLIC",
            collection_acron="scl",
        )

        self.assertEqual(mock_process_apply_async.call_count, 2)

    @patch("publication.tasks.Article.article_langs", new_callable=PropertyMock)
    @patch("publication.tasks.process_article_availability.apply_async")
    def test_initiate_article_availability_check_all_collections(
        self,
        mock_process_apply_async,
        mock_property_article_langs,
    ):
        mock_property_article_langs.side_effect = ["pt", "es"]
        initiate_article_availability_check(
            user_id=1, username="user_test", purpose="PUBLIC"
        )

        self.assertEqual(mock_process_apply_async.call_count, 4)

    @patch("publication.tasks.fetch_data_and_register_result.apply_async")
    def test_process_article_availability_call_times(self, mock_apply_async):
        process_article_availability(
            user_id=None,
            username="user_test",
            pid_v3=self.article.pid_v3,
            pid_v2=self.article.pid_v2,
            journal_acron=self.article.journal.journal_acron,
            lang="en",
            domain=self.web_site_configuration_scl.url,
        )
        process_article_availability(
            user_id=None,
            username="user_test",
            pid_v3=self.article.pid_v3,
            pid_v2=self.article.pid_v2,
            journal_acron=self.article.journal.journal_acron,
            lang="pt",
            domain=self.web_site_configuration_scl.url,
        )
        self.assertEqual(mock_apply_async.call_count, 8)

    @patch("publication.tasks.fetch_data")
    def test_fetch_data_and_register_result_some_fail(self, mock_fetch_data):
        mock_fetch_data.side_effect = [
            RetryableError,
            "mock content",
            "mock content",
            NonRetryableError,
        ]
        urls = self.get_url(
            domain=self.web_site_configuration_scl.url,
            journal_acron=self.journal.journal_acron,
            pid_v2=self.article.pid_v2,
            pid_v3=self.article.pid_v3,
            lang="en",
        )
        for url in urls:
            fetch_data_and_register_result(
                user_id=None,
                username="user_test",
                pid_v3=self.article.pid_v3,
                url=url,
            )
        self.assertEqual(mock_fetch_data.call_count, 4)

        scielo_url_status_first = ScieloURLStatus.objects.filter(
            available=False
        ).first()
        scielo_url_status_last = ScieloURLStatus.objects.filter(available=False).last()

        self.assertEqual(ScieloURLStatus.objects.filter(available=False).count(), 2)
        self.assertEqual(scielo_url_status_first.available, False)
        self.assertEqual(scielo_url_status_last.available, False)
        self.assertEqual(
            scielo_url_status_first.url,
            f"{self.web_site_configuration_scl.url}/scielo.php?script=sci_arttext&pid={self.article.pid_v2}&lang=en&nrm=iso",
        )
        self.assertEqual(
            scielo_url_status_last.url,
            f"{self.web_site_configuration_scl.url}/j/{self.article.journal.journal_acron}/a/{self.article.pid_v3}/?format=pdf&lang=en",
        )

    @patch("publication.tasks.fetch_data")
    def test_process_article_avaibility_fail_and_success(self, mock_fetch_data):
        mock_fetch_data.side_effect = [
            RetryableError,
            "mock content",
            "mock content",
            "mock content",
        ]
        urls = self.get_url(
            domain=self.web_site_configuration_scl.url,
            journal_acron=self.journal.journal_acron,
            pid_v2=self.article.pid_v2,
            pid_v3=self.article.pid_v3,
            lang="en",
        )
        for url in urls:
            fetch_data_and_register_result(
                user_id=None,
                username="user_test",
                pid_v3=self.article.pid_v3,
                url=url,
            )
        self.assertEqual(mock_fetch_data.call_count, 4)

        scielo_url_status_first = ScieloURLStatus.objects.filter(
            available=False
        ).first()

        self.assertEqual(ScieloURLStatus.objects.filter(available=False).count(), 1)
        self.assertEqual(scielo_url_status_first.available, False)
        self.assertEqual(
            scielo_url_status_first.url,
            f"{self.web_site_configuration_scl.url}/scielo.php?script=sci_arttext&pid={self.article.pid_v2}&lang=en&nrm=iso",
        )

        mock_fetch_data.side_effect = [
            "mock content",
            "mock content",
            "mock content",
            "mock content",
        ]
        for url in urls:
            fetch_data_and_register_result(
                user_id=None,
                username="user_test",
                pid_v3=self.article.pid_v3,
                url=url,
            )

        self.assertEqual(ScieloURLStatus.objects.filter(available=False).count(), 0)

    @patch("publication.tasks.fetch_data_and_register_result.apply_async")
    def test_retry_failed_scielo_urls(self, mock_apply_async):
        article_availability = ArticleAvailability.objects.create(
            article=self.article, creator=self.user
        )
        ScieloURLStatus.objects.create(
            article_availability=article_availability,
            url="https://www.example.com",
            available=False,
            creator=self.user,
        )
        expected_calls = [
            call(
                kwargs={
                    "pid_v3": "test_pid_v3",
                    "url": "https://www.example.com",
                    "username": "user_test",
                    "user_id": None,
                }
            )
        ]
        retry_failed_scielo_urls(username="user_test")
        self.assertEqual(mock_apply_async.call_count, 1)
        mock_apply_async.assert_has_calls(expected_calls, any_order=False)


class CollectionVerificationFileTest(TestCase):
    @classmethod
    def create_gzip_file(cls, content, file_name="test_file_pid_v2.txt.gz"):
        txt_content = "\n".join(content).encode("utf-8")

        gzip_file = SimpleUploadedFile(file_name, b"")
        with gzip.GzipFile(fileobj=gzip_file, mode="wb") as gz:
            gz.write(txt_content)

        gzip_file.seek(0)
        return gzip_file

    def setUp(
        self,
    ):
        self.user = User.objects.create(username="user_test")
        self.collection_scl = Collection.objects.create(acron="scl", creator=self.user)
        self.list_of_pids_v2_file = [
            "S0104-12902018000200XX1",
            "S0104-12902018000200556",
            "S0104-12902018000200298",
            "S0104-12902018000200423",
            "S0104-12902018000200XX4",
            "S0104-12902018000200495",
            "S0104-12902018000200481",
            "S0104-12902018000200338",
            "S0104-12902018000200588",
            "S0104-12902018000200544",
            "S0104-12902018000200435",
        ]

        self.list_of_pids_v2_migrated_article = [
            "S0104-12902018000200495",
            "S0104-12902018000200481",
            "S0104-12902018000200338",
            "S0104-12902018000200588",
            "S0104-12902018000200544",
            "S0104-12902018000200435",
            "S0104-12902018000200XX4",
        ]

        for v2 in self.list_of_pids_v2_migrated_article:
            MigratedArticle.objects.create(
                pid=v2,
                creator=self.user,
            )

        gzip_file = self.create_gzip_file(content=self.list_of_pids_v2_file)

        self.collection_file = CollectionVerificationFile.objects.create(
            collection=self.collection_scl,
            uploaded_file=gzip_file,
            creator=self.user,
        )

    def test_upload_to_function(self):
        expected_path = f"verification_article_files/{self.collection_scl}"
        media_root_path = f"/app/core/media/{expected_path}"
        self.assertTrue(
            self.collection_file.uploaded_file.name.startswith(expected_path)
        )
        self.assertTrue(
            self.collection_file.uploaded_file.path.startswith(media_root_path)
        )
        with gzip.open(self.collection_file.uploaded_file.path, "rt") as f:
            lines = f.read().splitlines()
            self.assertEqual(lines, self.list_of_pids_v2_file)

    @patch("publication.tasks.create_or_updated_migrated_article.apply_async")
    def test_process_file_to_check_migrated_articles(self, mock_apply_async):
        process_file_to_check_migrated_articles(
            username="user_test", collection_acron="scl"
        )

        missing_pids = set(self.list_of_pids_v2_file) - set(
            self.list_of_pids_v2_migrated_article
        )
        expected_calls = [
            {
                "pid_v2": pid_v2,
                "collection_acron": "scl",
                "username": "user_test",
            }
            for pid_v2 in missing_pids
        ]

        self.assertEqual(mock_apply_async.call_count, len(missing_pids))
        self.assertEqual(
            set(tuple(call.kwargs.items()) for call in mock_apply_async.call_args_list),
            set(tuple(expected_call.items()) for expected_call in expected_calls),
        )

    def test_create_or_updated_migrated_article(
        self,
    ):
        create_or_updated_migrated_article(
            self.list_of_pids_v2_file[0], self.collection_scl.acron, self.user.username
        )
        migrated_article = MigratedArticle.objects.get(pid=self.list_of_pids_v2_file[0])

        self.assertEqual(migrated_article.pid, self.list_of_pids_v2_file[0])
        self.assertEqual(migrated_article.collection, self.collection_scl)
        self.assertEqual(migrated_article.migration_status, "PENDING")
