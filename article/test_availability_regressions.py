from datetime import timedelta
from unittest import TestCase as UnitTestCase
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from article import page_checker
from article.models import Article, ArticleCollection, ArticleWebPage
from collection.models import Collection, WebSiteConfiguration
from core.utils.requester import NonRetryableError, RetryableError
from journal.models import Journal
from proc.models import JournalProc
from publication import models as publication_models


class ArticlePageRebuildTests(TestCase):
    def test_pages_rebuild_only_when_missing_stale_or_forced(self):
        user = get_user_model().objects.create_user(username="pages-review")
        collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=user
        )
        journal = Journal.objects.create(creator=user)
        JournalProc.objects.create(journal=journal, collection=collection, creator=user)
        article = Article.objects.create(journal=journal, creator=user)
        config = WebSiteConfiguration.objects.create(
            collection=collection,
            creator=user,
            enabled=True,
            purpose="QA",
            url="https://old.example",
        )
        item = {
            "url": "https://old.example/article",
            "purpose": "QA",
            "format": "html",
            "lang": None,
        }

        with patch.object(Article, "get_webpage_items", return_value=[item]) as pages:
            article.create_or_update_article_collections(user)
            pages.assert_called_once_with(config.url, "QA")
            article_collection = article.article_collections.get()
            WebSiteConfiguration.objects.create(
                collection=collection, creator=user, enabled=False, purpose="PUBLIC"
            )
            pages.reset_mock()
            result = article.create_or_update_article_collections(user)
            pages.assert_not_called()
            self.assertEqual(result, [article_collection])

            article.create_or_update_article_collections(user, force_update=True)
            pages.assert_called_once_with(config.url, "QA")
            ArticleWebPage.objects.create(
                article=article,
                collection=collection,
                creator=user,
                purpose="QA",
                fmt="pdf",
                url="https://old.example/article.pdf",
            )
            ArticleCollection.objects.filter(pk=article_collection.pk).update(
                updated=timezone.now() - timedelta(days=1)
            )
            config.url = "https://new.example"
            config.save()
            item["url"] = "https://new.example/article"
            article.create_or_update_article_collections(user)

        self.assertEqual(
            list(article.pages.values_list("url", flat=True)), [item["url"]]
        )
        article_collection.refresh_from_db()
        self.assertFalse(article_collection.is_stale())


class AvailabilityRequestTests(UnitTestCase):
    def test_network_errors_are_reported_as_unavailability(self):
        for error_type in (NonRetryableError, RetryableError):
            with self.subTest(error=error_type.__name__):
                with patch.object(
                    page_checker, "fetch_data", side_effect=error_type("network")
                ):
                    self.assertEqual(
                        page_checker.check_url("https://example.org/article", 7)[
                            "error"
                        ],
                        "network",
                    )
                with patch.object(
                    publication_models, "fetch_data", side_effect=error_type("network")
                ):
                    self.assertFalse(
                        publication_models.check_url("https://example.org/article", 7)
                    )

    def test_unexpected_errors_propagate(self):
        for module in (page_checker, publication_models):
            with self.subTest(module=module.__name__):
                with patch.object(module, "fetch_data", side_effect=TypeError("bug")):
                    with self.assertRaises(TypeError):
                        module.check_url("https://example.org/article", 7)

    def test_legacy_availability_extracts_url_from_webpage_item(self):
        availability = MagicMock()
        availability.article.get_webpage_items.return_value = [
            {"url": "https://example.org/article"}
        ]
        with patch.object(
            publication_models.ScieloURLStatus, "create_or_update"
        ) as create:
            publication_models.ArticleAvailability.create_or_update_urls(
                availability, "USER", "https://example.org", timeout=7
            )

        create.assert_called_once_with(
            user="USER",
            article=availability.article,
            url="https://example.org/article",
            timeout=7,
        )
