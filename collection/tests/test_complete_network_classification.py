from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from collection.network_classification_completion import (
    infer_network_classification,
)

User = get_user_model()


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

        self.assertEqual(result, {"updated": [], "inferred": [], "not_found": ["xyz"]})
        self.assertIsNone(Collection.objects.get(acron="xyz").network_classification)

    @patch("collection.network_classification_completion.fetch_data")
    def test_does_not_fetch_when_all_collections_are_complete(self, mock_fetch_data):
        Collection.objects.create(
            acron="scl", network_classification=["scielonetwork"], creator=self.user
        )

        result = Collection.complete_network_classification(self.user)

        self.assertEqual(result, {"updated": [], "inferred": [], "not_found": []})
        mock_fetch_data.assert_not_called()

    @patch("collection.network_classification_completion.fetch_data")
    def test_fetches_articlemeta_when_data_is_not_given(self, mock_fetch_data):
        mock_fetch_data.return_value = self.collections_data
        Collection.objects.create(acron="scl", creator=self.user)

        result = Collection.complete_network_classification(self.user)

        self.assertEqual(result["updated"], ["scl"])
        mock_fetch_data.assert_called_once()


class CompleteNetworkClassificationMigrationTest(TestCase):
    """
    A migração collection 0007_complete_network_classification usa a mesma
    função da tarefa, com os modelos históricos, e nunca falha
    """

    def setUp(self):
        self.user = User.objects.create(username="tester")
        patcher = patch(
            "collection.network_classification_completion.fetch_data",
            return_value=[
                {"acron": "scl", "network_classification": ["scielonetwork"]},
            ],
        )
        self.mock_fetch_data = patcher.start()
        self.addCleanup(patcher.stop)

    def historical_apps(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        return executor.loader.project_state(
            ("collection", "0007_complete_network_classification")
        ).apps

    def run_migration(self):
        import importlib

        migration = importlib.import_module(
            "collection.migrations.0007_complete_network_classification"
        )
        migration.complete_network_classification(self.historical_apps(), None)

    def test_completes_collections_without_network_classification(self):
        Collection.objects.create(acron="scl", creator=self.user)
        Collection.objects.create(acron="xyz", creator=self.user)

        self.run_migration()

        self.assertTrue(
            Collection.objects.get(acron="scl").is_national_journal_collection
        )
        self.assertIsNone(Collection.objects.get(acron="xyz").network_classification)
        self.mock_fetch_data.assert_called_once()

    def test_does_not_fetch_when_all_collections_are_complete(self):
        Collection.objects.create(
            acron="scl", network_classification=["thematic"], creator=self.user
        )

        self.run_migration()

        self.mock_fetch_data.assert_not_called()
        self.assertEqual(
            Collection.objects.get(acron="scl").network_classification, ["thematic"]
        )

    def test_infers_by_name_when_articlemeta_fails(self):
        self.mock_fetch_data.side_effect = Exception("articlemeta indisponível")
        Collection.objects.create(acron="scl", name="SciELO Brasil", creator=self.user)
        Collection.objects.create(acron="psi", name="Pepsic", creator=self.user)
        Collection.objects.create(acron="xyz", creator=self.user)

        self.run_migration()

        self.assertEqual(
            Collection.objects.get(acron="scl").network_classification,
            ["scielonetwork"],
        )
        self.assertEqual(
            Collection.objects.get(acron="psi").network_classification, ["thematic"]
        )
        # sem nome: não infere
        self.assertIsNone(Collection.objects.get(acron="xyz").network_classification)


class InferNetworkClassificationTest(TestCase):
    def test_public_health_is_scielonetwork_and_thematic(self):
        for name in ("SciELO Saúde Pública", "SciELO Salud Pública", "SciELO Public Health"):
            with self.subTest(name=name):
                self.assertEqual(
                    infer_network_classification(name), ["scielonetwork", "thematic"]
                )

    def test_country_is_scielonetwork(self):
        for name in (
            "SciELO Brasil",
            "SciELO México",
            "SciELO España",
            "SciELO Perú",
            "SciELO South Africa",
            "SciELO República Dominicana",
            "Chile",
        ):
            with self.subTest(name=name):
                self.assertEqual(infer_network_classification(name), ["scielonetwork"])

    def test_others_are_thematic(self):
        for name in ("Pepsic", "REVENF", "SciELO Social Sciences", "SciELO Preprints"):
            with self.subTest(name=name):
                self.assertEqual(infer_network_classification(name), ["thematic"])

    def test_without_name(self):
        for name in (None, "", "  "):
            with self.subTest(name=name):
                self.assertIsNone(infer_network_classification(name))


class CompleteNetworkClassificationInferenceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="tester")

    def test_articlemeta_has_priority_and_missing_collections_are_inferred(self):
        Collection.objects.create(acron="scl", name="SciELO Brasil", creator=self.user)
        Collection.objects.create(
            acron="spa", name="SciELO Saúde Pública", creator=self.user
        )

        result = Collection.complete_network_classification(
            self.user,
            collections_data=[{"acron": "scl", "network_classification": ["thematic"]}],
        )

        self.assertEqual(sorted(result["updated"]), ["scl", "spa"])
        self.assertEqual(result["inferred"], ["spa"])
        self.assertEqual(
            Collection.objects.get(acron="scl").network_classification, ["thematic"]
        )
        self.assertEqual(
            Collection.objects.get(acron="spa").network_classification,
            ["scielonetwork", "thematic"],
        )

    @patch(
        "collection.network_classification_completion.fetch_data",
        side_effect=Exception("articlemeta indisponível"),
    )
    def test_infers_all_when_articlemeta_fails(self, mock_fetch_data):
        Collection.objects.create(acron="scl", name="SciELO Brasil", creator=self.user)

        result = Collection.complete_network_classification(self.user)

        self.assertEqual(result["updated"], ["scl"])
        self.assertEqual(result["inferred"], ["scl"])
        self.assertIn("articlemeta_error", result)
