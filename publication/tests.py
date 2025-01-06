import gzip
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from unittest.mock import patch

from .tasks import (
    initiate_article_availability_check,
    process_article_availability,
    process_file_to_check_migrated_articles,
)
from .models import (
    ScieloURLStatus,
    ArticleAvailability,
    CollectionVerificationFile,
    MissingArticle,
)
from article.models import Article, ArticleDOIWithLang
from collection.models import Collection, WebSiteConfiguration
from issue.models import Issue
from journal.models import Journal
from proc.models import JournalProc
from core.users.models import User
from core.utils.requester import RetryableError, NonRetryableError


class ArticleAvailabilityTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="user_test")
        self.collection = Collection.objects.create(acron="scl", creator=self.user)
        self.web_site_configuration = WebSiteConfiguration.objects.create(
            creator=self.user,
            collection=self.collection,
            url="https://mocked-domain.com",
            enabled=True,
        )
        self.journal = Journal.objects.create(
            official_journal=None, journal_acron="scl", creator=self.user
        )
        self.journal_proc = JournalProc.objects.create(
            journal=self.journal,
            collection=self.collection,
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

    @patch("publication.tasks.process_article_availability.apply_async")
    def test_initiate_article_availability_check(
        self,
        mock_process_apply_async,
    ):
        initiate_article_availability_check(
            user_id=1, username="user_test", collection_acron="scl"
        )

        self.assertEqual(mock_process_apply_async.call_count, 2)

    @patch("publication.tasks.fetch_data")
    def test_process_article_availability_success(self, mock_fetch_data):
        mock_fetch_data.return_value = "mock content"

        process_article_availability(
            user_id=None,
            username="user_test",
            pid_v3=self.article.pid_v3,
            pid_v2=self.article.pid_v2,
            journal_acron=self.article.journal.journal_acron,
            lang="en",
            domain=self.web_site_configuration.url,
        )
        process_article_availability(
            user_id=None,
            username="user_test",
            pid_v3=self.article.pid_v3,
            pid_v2=self.article.pid_v2,
            journal_acron=self.article.journal.journal_acron,
            lang="pt",
            domain=self.web_site_configuration.url,
        )
        self.assertEqual(mock_fetch_data.call_count, 8)
        self.assertEqual(ArticleAvailability.objects.all().count(), 0)
        self.assertEqual(ScieloURLStatus.objects.all().count(), 0)

    @patch("publication.tasks.fetch_data")
    def test_process_article_avaibility_some_fail(self, mock_fetch_data):
        mock_fetch_data.side_effect = [
            RetryableError,
            "mock content",
            "mock content",
            NonRetryableError,
        ]
        process_article_availability(
            user_id=None,
            username="user_test",
            pid_v3=self.article.pid_v3,
            pid_v2=self.article.pid_v2,
            journal_acron=self.article.journal.journal_acron,
            lang=self.doi_en.lang,
            domain=self.web_site_configuration.url,
        )
        self.assertEqual(mock_fetch_data.call_count, 4)

        scielo_url_status_first = ScieloURLStatus.objects.filter(
            available=False
        ).first()
        scielo_url_status_last = ScieloURLStatus.objects.filter(available=False).last()

        self.assertEqual(ScieloURLStatus.objects.filter(available=False).count(), 2)
        self.assertEqual(scielo_url_status_first.status, str(RetryableError))
        self.assertEqual(scielo_url_status_last.status, str(NonRetryableError))
        self.assertEqual(scielo_url_status_first.available, False)
        self.assertEqual(scielo_url_status_last.available, False)
        self.assertEqual(
            scielo_url_status_first.url,
            f"{self.web_site_configuration.url}/scielo.php?script=sci_arttext&pid={self.article.pid_v2}&lang={self.doi_en.lang}&nrm=iso",
        )
        self.assertEqual(
            scielo_url_status_last.url,
            f"{self.web_site_configuration.url}/j/{self.article.journal.journal_acron}/a/{self.article.pid_v3}/?format=pdf&lang={self.doi_en.lang}",
        )

    @patch("publication.tasks.fetch_data")
    def test_process_article_avaibility_fail_and_success(self, mock_fetch_data):
        mock_fetch_data.side_effect = [
            RetryableError,
            "mock content",
            "mock content",
            "mock content",
        ]
        process_article_availability(
            user_id=None,
            username="user_test",
            pid_v3=self.article.pid_v3,
            pid_v2=self.article.pid_v2,
            journal_acron=self.article.journal.journal_acron,
            lang=self.doi_en.lang,
            domain=self.web_site_configuration.url,
        )
        self.assertEqual(mock_fetch_data.call_count, 4)

        scielo_url_status_first = ScieloURLStatus.objects.filter(
            available=False
        ).first()

        self.assertEqual(ScieloURLStatus.objects.filter(available=False).count(), 1)
        self.assertEqual(scielo_url_status_first.status, str(RetryableError))
        self.assertEqual(scielo_url_status_first.available, False)
        self.assertEqual(
            scielo_url_status_first.url,
            f"{self.web_site_configuration.url}/scielo.php?script=sci_arttext&pid={self.article.pid_v2}&lang={self.doi_en.lang}&nrm=iso",
        )

        mock_fetch_data.side_effect = [
            "mock content",
            "mock content",
            "mock content",
            "mock content",
        ]
        process_article_availability(
            user_id=None,
            username="user_test",
            pid_v3=self.article.pid_v3,
            pid_v2=self.article.pid_v2,
            journal_acron=self.article.journal.journal_acron,
            lang=self.doi_en.lang,
            domain=self.web_site_configuration.url,
        )

        self.assertEqual(ScieloURLStatus.objects.filter(available=False).count(), 0)


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
        self.collection = Collection.objects.create(acron="scl", creator=self.user)
        self.list_of_pids_v2 = [
            "S0104-12902018000200XX1",
            "S0104-12902018000200XX4",
            "S0104-12902018000200556",
            "S0104-12902018000200298",
            "S0104-12902018000200423",
            "S0104-12902018000200495",
            "S0104-12902018000200481",
            "S0104-12902018000200338",
            "S0104-12902018000200588",
            "S0104-12902018000200544",
            "S0104-12902018000200435",
            "S0104-12902018000200XX4",
        ]

        for v2 in self.list_of_pids_v2[:4]:
            Article.objects.create(
                pid_v2=v2,
                creator=self.user,
            )

        gzip_file = self.create_gzip_file(content=self.list_of_pids_v2[4:])

        self.instance = CollectionVerificationFile.objects.create(
            collection=self.collection,
            uploaded_file=gzip_file,
            creator=self.user,
        )

    def test_upload_to_function(self):
        expected_path = f"verification_article_files/{self.collection}"
        media_root_path = f"/app/core/media/{expected_path}"
        self.assertTrue(self.instance.uploaded_file.name.startswith(expected_path))
        self.assertTrue(self.instance.uploaded_file.path.startswith(media_root_path))
        with gzip.open(self.instance.uploaded_file.path, "rt") as f:
            lines = f.read().splitlines()
            self.assertEqual(lines, self.list_of_pids_v2[4:])

    @patch("publication.tasks.create_or_update_missing_article.apply_async")
    def test_process_file_to_check_migrated_articles(self, mock_apply_async):
        process_file_to_check_migrated_articles(
            username="user_test", collection_acron="scl"
        )

        missing_pids = set(self.list_of_pids_v2[4:]) - set(self.list_of_pids_v2[:4])
        expected_calls = [
            {
                "pid_v2": pid_v2,
                "collection_verification_file_id": self.instance.id,
                "username": "user_test",
            }
            for pid_v2 in missing_pids
        ]
        self.assertEqual(mock_apply_async.call_count, len(missing_pids))        
        self.assertEqual(set(tuple(call.kwargs.items()) for call in mock_apply_async.call_args_list), set(tuple(expected_call.items()) for expected_call in expected_calls))

    def test_create_or_update_missing_articles(self,):
        MissingArticle.create_or_update(
            pid_v2="S0104-12902018000200XX4",
            collection_file=self.instance,
            user=self.user,
        )

        self.assertEqual(MissingArticle.objects.count(), 1)