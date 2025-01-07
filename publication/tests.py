from django.db.models import Q
from django.test import TestCase
from unittest.mock import patch

from .tasks import initiate_article_availability_check, process_article_availability, fetch_data_and_register_result
from .models import ScieloURLStatus, ArticleAvailability
from article.models import Article, ArticleDOIWithLang
from collection.models import Collection, WebSiteConfiguration
from issue.models import Issue
from journal.models import Journal
from proc.models import JournalProc
from core.users.models import User
from core.utils.requester import RetryableError, NonRetryableError


class ArticleAvailabilityTeste(TestCase):
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
        self.urls = [
            f"{self.web_site_configuration.url}/scielo.php?script=sci_arttext&pid={self.article.pid_v2}&lang={self.doi_en.lang}&nrm=iso",
            f"{self.web_site_configuration.url}/j/{self.article.journal.journal_acron}/a/{self.article.pid_v3}/?lang={self.doi_en.lang}",
            f"{self.web_site_configuration.url}/scielo.php?script=sci_arttext&pid={self.article.pid_v2}&format=pdf&lng={self.doi_en.lang}&nrm=iso",
            f"{self.web_site_configuration.url}/j/{self.article.journal.journal_acron}/a/{self.article.pid_v3}/?format=pdf&lang={self.doi_en.lang}",
        ]

    @patch("publication.tasks.process_article_availability.apply_async")
    def test_initiate_article_availability_check(
        self,
        mock_process_apply_async,
    ):
        initiate_article_availability_check(
            user_id=1, username="user_test", collection_acron="scl"
        )

        self.assertEqual(mock_process_apply_async.call_count, 2)

    @patch("publication.tasks.fetch_data_and_register_result.apply_async")
    def test_process_article_availability_call_times(self, mock_apply_async):
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
        self.assertEqual(mock_apply_async.call_count, 8)

    @patch("publication.tasks.fetch_data")
    def test_fetch_data_and_register_result_some_fail(self, mock_fetch_data):
        mock_fetch_data.side_effect = [
            RetryableError,
            "mock content",
            "mock content",
            NonRetryableError,
        ]
        for url in self.urls:
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
        for url in self.urls:
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
        for url in self.urls:
            fetch_data_and_register_result(
                user_id=None,
                username="user_test",
                pid_v3=self.article.pid_v3,
                url=url,
            )

        self.assertEqual(ScieloURLStatus.objects.filter(available=False).count(), 0)
