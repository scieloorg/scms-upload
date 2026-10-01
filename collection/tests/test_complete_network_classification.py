from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from collection.models import (
    ENSURE_NETWORK_CLASSIFICATION_CACHE_KEY,
    Collection,
    normalize_network_classification,
)
from collection.tasks import task_complete_network_classification

User = get_user_model()


class NormalizeNetworkClassificationTest(TestCase):
    def test_converts_str_to_list(self):
        self.assertEqual(
            normalize_network_classification("thematic"), ["thematic"]
        )

    def test_ignores_empty_items(self):
        self.assertEqual(
            normalize_network_classification(["", None, "thematic"]), ["thematic"]
        )

    def test_returns_none_when_empty(self):
        self.assertIsNone(normalize_network_classification(None))
        self.assertIsNone(normalize_network_classification(""))
        self.assertIsNone(normalize_network_classification([]))
        self.assertIsNone(normalize_network_classification([""]))


class CompleteNetworkClassificationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="tester")
        self.collections_data = [
            {"acron": "scl", "network_classification": ["scielonetwork"]},
            {"acron": "spa", "network_classification": ["scielonetwork", "thematic"]},
            {"acron": "psi", "network_classification": "thematic"},
            {"acron": "pef", "network_classification": ["independent"]},
        ]

    def test_completes_only_collections_without_network_classification(self):
        Collection.objects.create(acron="scl", creator=self.user)
        Collection.objects.create(
            acron="spa", network_classification=[], creator=self.user
        )
        Collection.objects.create(acron="psi", creator=self.user)
        Collection.objects.create(
            acron="pef", network_classification=["thematic"], creator=self.user
        )

        result = Collection.complete_network_classification(
            self.user, collections_data=self.collections_data
        )

        self.assertEqual(sorted(result["updated"]), ["psi", "scl", "spa"])
        self.assertEqual(result["not_found"], [])
        self.assertEqual(
            Collection.objects.get(acron="scl").network_classification,
            ["scielonetwork"],
        )
        self.assertEqual(
            Collection.objects.get(acron="spa").network_classification,
            ["scielonetwork", "thematic"],
        )
        self.assertEqual(
            Collection.objects.get(acron="psi").network_classification,
            ["thematic"],
        )
        # já preenchida: mantém o valor atual
        self.assertEqual(
            Collection.objects.get(acron="pef").network_classification,
            ["thematic"],
        )
        self.assertEqual(Collection.objects.get(acron="scl").updated_by, self.user)

    def test_completed_collection_becomes_national_journal_collection(self):
        Collection.objects.create(acron="scl", creator=self.user)
        Collection.objects.create(acron="psi", creator=self.user)

        Collection.complete_network_classification(
            self.user, collections_data=self.collections_data
        )

        self.assertTrue(Collection.objects.get(acron="scl").is_national_journal_collection)
        self.assertFalse(Collection.objects.get(acron="psi").is_national_journal_collection)
        self.assertEqual(
            list(
                Collection.get_national_journal_collections().values_list(
                    "acron", flat=True
                )
            ),
            ["scl"],
        )

    def test_reports_collections_absent_from_source(self):
        Collection.objects.create(acron="xyz", creator=self.user)

        result = Collection.complete_network_classification(
            self.user, collections_data=self.collections_data
        )

        self.assertEqual(result, {"updated": [], "not_found": ["xyz"]})
        self.assertIsNone(Collection.objects.get(acron="xyz").network_classification)

    @patch("collection.models.fetch_data")
    def test_does_not_fetch_when_all_collections_are_complete(self, mock_fetch_data):
        Collection.objects.create(
            acron="scl", network_classification=["scielonetwork"], creator=self.user
        )

        result = Collection.complete_network_classification(self.user)

        self.assertEqual(result, {"updated": [], "not_found": []})
        mock_fetch_data.assert_not_called()

    @patch("collection.models.fetch_data")
    def test_fetches_articlemeta_when_data_is_not_given(self, mock_fetch_data):
        mock_fetch_data.return_value = self.collections_data
        Collection.objects.create(acron="scl", creator=self.user)

        result = Collection.complete_network_classification(self.user)

        self.assertEqual(result["updated"], ["scl"])
        mock_fetch_data.assert_called_once()


@override_settings(COLLECTION_ENSURE_NETWORK_CLASSIFICATION=True)
class EnsureNetworkClassificationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="tester")
        cache.delete(ENSURE_NETWORK_CLASSIFICATION_CACHE_KEY)
        self.addCleanup(cache.delete, ENSURE_NETWORK_CLASSIFICATION_CACHE_KEY)
        patcher = patch(
            "collection.models.fetch_data",
            return_value=[
                {"acron": "scl", "network_classification": ["scielonetwork"]},
            ],
        )
        self.mock_fetch_data = patcher.start()
        self.addCleanup(patcher.stop)

    def test_completes_collections_without_network_classification(self):
        Collection.objects.create(acron="scl", creator=self.user)

        result = Collection.ensure_network_classification(self.user)

        self.assertEqual(result, {"updated": ["scl"], "not_found": []})
        self.assertTrue(Collection.objects.get(acron="scl").is_national_journal_collection)
        self.mock_fetch_data.assert_called_once()

    def test_does_not_fetch_when_all_collections_are_complete(self):
        Collection.objects.create(
            acron="scl", network_classification=["scielonetwork"], creator=self.user
        )

        self.assertIsNone(Collection.ensure_network_classification(self.user))
        self.mock_fetch_data.assert_not_called()

    def test_fetches_at_most_once_per_interval(self):
        # coleção ausente no articlemeta continua sem network_classification
        Collection.objects.create(acron="xyz", creator=self.user)

        result = Collection.ensure_network_classification(self.user)
        self.assertEqual(result, {"updated": [], "not_found": ["xyz"]})
        self.assertIsNone(Collection.ensure_network_classification(self.user))
        self.mock_fetch_data.assert_called_once()

        # após o intervalo, consulta novamente
        cache.delete(ENSURE_NETWORK_CLASSIFICATION_CACHE_KEY)
        Collection.ensure_network_classification(self.user)
        self.assertEqual(self.mock_fetch_data.call_count, 2)

    def test_does_not_raise_when_articlemeta_fails(self):
        self.mock_fetch_data.side_effect = Exception("articlemeta indisponível")
        Collection.objects.create(acron="scl", creator=self.user)

        self.assertIsNone(Collection.ensure_network_classification(self.user))
        self.assertIsNone(Collection.objects.get(acron="scl").network_classification)

    @override_settings(COLLECTION_ENSURE_NETWORK_CLASSIFICATION=False)
    def test_does_nothing_when_disabled(self):
        Collection.objects.create(acron="scl", creator=self.user)

        self.assertIsNone(Collection.ensure_network_classification(self.user))
        self.mock_fetch_data.assert_not_called()
        self.assertIsNone(Collection.objects.get(acron="scl").network_classification)


class TaskCompleteNetworkClassificationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="tester")

    @patch("collection.models.fetch_data")
    def test_task_completes_network_classification(self, mock_fetch_data):
        mock_fetch_data.return_value = [
            {"acron": "scl", "network_classification": ["scielonetwork"]},
        ]
        Collection.objects.create(acron="scl", creator=self.user)

        result = task_complete_network_classification.run(username="tester")

        self.assertEqual(result, {"updated": ["scl"], "not_found": []})
        self.assertEqual(
            Collection.objects.get(acron="scl").network_classification,
            ["scielonetwork"],
        )

    def test_task_requires_user(self):
        with self.assertRaises(ValueError):
            task_complete_network_classification.run()
