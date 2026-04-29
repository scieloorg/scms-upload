"""Tests for publication.api.publication.get_api_data caching."""
import unittest
from unittest.mock import patch

from publication.api import publication as publication_module
from publication.api.publication import (
    clear_api_data_cache,
    get_api_data,
)


class _FakeCollection:
    def __init__(self, pk):
        self.pk = pk

    def __str__(self):
        return f"Collection({self.pk})"


class GetApiDataCacheTest(unittest.TestCase):
    def setUp(self):
        clear_api_data_cache()

    def tearDown(self):
        clear_api_data_cache()

    def test_caches_successful_response_per_key(self):
        collection = _FakeCollection(pk=1)
        with patch.object(
            publication_module,
            "get_api",
            return_value={"token": "abc", "post_data_url": "http://x"},
        ) as mocked:
            first = get_api_data(collection, "issue", "QA")
            second = get_api_data(collection, "issue", "QA")
            third = get_api_data(collection, "issue", "PUBLIC")

        # Mesma collection/content_type/website_kind: chamado 1x.
        # Chave diferente para PUBLIC: 1x adicional.
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(first["token"], "abc")
        self.assertEqual(second["token"], "abc")
        self.assertEqual(third["token"], "abc")

    def test_returns_copy_so_caller_mutation_does_not_poison_cache(self):
        collection = _FakeCollection(pk=2)
        with patch.object(
            publication_module,
            "get_api",
            return_value={"token": "t", "post_data_url": "u", "nested": {"x": 1}},
        ):
            first = get_api_data(collection, "article", "PUBLIC")
            first["verify"] = True  # mutação como em task_publish_articles
            first["nested"]["x"] = 999  # mutação aninhada
            second = get_api_data(collection, "article", "PUBLIC")

        self.assertNotIn("verify", second)
        self.assertEqual(second["nested"]["x"], 1)

    def test_does_not_cache_error_responses(self):
        collection = _FakeCollection(pk=3)
        # Primeira chamada retorna erro, segunda retorna sucesso.
        responses = iter([
            {"error": "boom"},
            {"token": "ok", "post_data_url": "u"},
        ])
        with patch.object(
            publication_module,
            "get_api",
            side_effect=lambda *a, **kw: next(responses),
        ) as mocked:
            err = get_api_data(collection, "issue", "QA")
            ok = get_api_data(collection, "issue", "QA")

        self.assertEqual(mocked.call_count, 2)
        self.assertIn("error", err)
        self.assertEqual(ok["token"], "ok")

    def test_clear_cache_helper(self):
        collection = _FakeCollection(pk=4)
        with patch.object(
            publication_module,
            "get_api",
            return_value={"token": "z"},
        ) as mocked:
            get_api_data(collection, "issue", "QA")
            clear_api_data_cache()
            get_api_data(collection, "issue", "QA")

        self.assertEqual(mocked.call_count, 2)
