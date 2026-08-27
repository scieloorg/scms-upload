from unittest.mock import PropertyMock, call, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from article.models import Article, ArticleDOIWithLang, ArticleCollection
from collection.models import Collection, WebSiteConfiguration, Language
from core.users.models import User
from core.utils.requester import NonRetryableError, RetryableError
from issue.models import Issue
from journal.models import Journal, JournalCollection, OfficialJournal
from proc.models import JournalProc

from publication.models import ArticleAvailability, ScieloURLStatus
from publication.tasks import (
    fetch_data_and_register_result,
    task_check_article_availability,
    process_article_availability,
    retry_failed_scielo_urls,
)


@patch.object(Article, "htmls", new_callable=PropertyMock, return_value=[])
@patch.object(Article, "pdfs", new_callable=PropertyMock, return_value=[])
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
        self.web_site_configuration_scl_qa = WebSiteConfiguration.objects.create(
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
        self.journal_proc_scl = JournalProc.objects.create(
            journal=self.journal,
            collection=self.collection_scl,
            acron="abdc",
            creator=self.user,
        )
        self.journal_proc_mex = JournalProc.objects.create(
            journal=self.journal,
            collection=self.collection_mex,
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
        lang = Language.get_or_create(creator=self.user, code2="en")
        self.doi_en = ArticleDOIWithLang.get_or_create(
            self.user, article=self.article, doi="10.1016/j.iheduc.2015.08.004", lang=lang)

        lang = Language.get_or_create(creator=self.user, code2="pt")
        self.doi_pt = ArticleDOIWithLang.get_or_create(
            self.user,
            article=self.article,
            doi="10.1016/j.iheduc.2015.08.004",
            lang=lang,
        )

    def get_url(self, domain, journal_acron, pid_v2, pid_v3, lang):
        return [
            f"{domain}/scielo.php?script=sci_arttext&pid={pid_v2}&lang={lang}&nrm=iso",
            f"{domain}/j/{journal_acron}/a/{pid_v3}/?lang={lang}",
            f"{domain}/scielo.php?script=sci_arttext&pid={pid_v2}&format=pdf&lng={lang}&nrm=iso",
            f"{domain}/j/{journal_acron}/a/{pid_v3}/?format=pdf&lang={lang}",
        ]

    @patch("publication.tasks.process_article_availability.apply_async")
    def test_task_check_article_availability_all_collections(
        self, mock_process_apply_async, mock_htmls, mock_pdfs
    ):
        # 2 JournalProcs (scl, mex) x WebSiteConfigurations associadas
        task_check_article_availability(
            username="user_test", purpose="PUBLIC"
        )
        self.assertEqual(mock_process_apply_async.call_count, 3)

    @patch("article.models.ArticleWebPage.check_page")
    def test_process_article_availability_call_times(
        self, mock_check_page, mock_htmls, mock_pdfs
    ):
        art_col = ArticleCollection.get_or_create(
            user=self.user,
            article=self.article,
            collection=self.collection_scl
        )
        art_col.create_or_update_pages(user=self.user)

        process_article_availability(
            pid_v3=self.article.pid_v3,
            domain=self.web_site_configuration_scl.url,
            user_id=self.user.id,
            username="user_test",
        )

        expected_pages_count = self.article.pages.count()
        self.assertEqual(mock_check_page.call_count, expected_pages_count)

    @patch("publication.models.ScieloURLStatus.update")
    def test_retry_failed_scielo_urls(self, mock_update, mock_htmls, mock_pdfs):
        article_availability = ArticleAvailability.objects.create(
            article=self.article, creator=self.user
        )
        ScieloURLStatus.objects.create(
            article_availability=article_availability,
            url="https://www.example.com",
            available=False,
            creator=self.user,
        )

        retry_failed_scielo_urls(username="user_test", pid_v3=self.article.pid_v3)

        self.assertEqual(mock_update.call_count, 1)