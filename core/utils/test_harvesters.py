from unittest import TestCase
from unittest.mock import patch

from core.utils.harvesters import OPACHarvester
from core.utils.requester import NonRetryableError


ITEM_JTEST = {
    "journal_acronym": "jtest",
    "pid_v1": "v1",
    "pid_v2": "S0001-00002024000100001",
    "publication_date": "2024-01-15",
    "default_language": "en",
    "aop_pid": None,
    "create": "Mon, 15 Jan 2024 10:00:00 GMT",
    "update": "Tue, 16 Jan 2024 12:00:00 GMT",
}

ITEM_JOTHER = {
    "journal_acronym": "jother",
    "pid_v1": "v1b",
    "pid_v2": "S0002-00002024000200001",
    "publication_date": "2024-06-01",
    "default_language": "pt",
    "aop_pid": None,
    "create": "Sat, 01 Jun 2024 08:00:00 GMT",
    "update": None,
}


def _make_harvester(**kwargs):
    defaults = dict(
        domain="www.example.com",
        collection_acron="scl",
        from_date="2024-01-01",
        until_date="2024-12-31",
        limit=10,
        timeout=2,
    )
    defaults.update(kwargs)
    return OPACHarvester(**defaults)


# ---------------------------------------------------------------------------
# harvest_documents
# ---------------------------------------------------------------------------

class HarvestDocumentsTest(TestCase):
    """Testa o contrato de harvest_documents: retorna tuplas (pid_v3, item_dict)."""

    @patch("core.utils.harvesters.fetch_data")
    def test_yields_tuples_pid_v3_and_raw_item(self, mock_fetch):
        """harvest_documents deve retornar tuplas (pid_v3, item) sem formatação."""
        mock_fetch.return_value = {
            "pages": 1,
            "documents": {"abc123": ITEM_JTEST},
        }
        harvester = _make_harvester()
        results = list(harvester.harvest_documents())

        self.assertEqual(len(results), 1)
        pid_v3, item = results[0]
        self.assertEqual(pid_v3, "abc123")
        self.assertEqual(item, ITEM_JTEST)

    @patch("core.utils.harvesters.fetch_data")
    def test_yields_all_documents_across_pages(self, mock_fetch):
        """Documentos de múltiplas páginas devem ser retornados em sequência."""
        mock_fetch.side_effect = [
            {"pages": 2, "documents": {"pid1": ITEM_JTEST}},
            {"pages": 2, "documents": {"pid2": ITEM_JOTHER}},
        ]
        harvester = _make_harvester()
        results = list(harvester.harvest_documents())

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], "pid1")
        self.assertEqual(results[1][0], "pid2")
        self.assertEqual(mock_fetch.call_count, 2)

    @patch("core.utils.harvesters.fetch_data")
    def test_stops_when_total_pages_is_zero(self, mock_fetch):
        """Deve parar sem erros quando pages=0 ou ausente."""
        mock_fetch.return_value = {"pages": 0, "documents": {}}
        harvester = _make_harvester()
        results = list(harvester.harvest_documents())

        self.assertEqual(results, [])
        self.assertEqual(mock_fetch.call_count, 1)

    @patch("core.utils.harvesters.fetch_data")
    def test_stops_when_documents_is_empty(self, mock_fetch):
        """Deve parar quando documents={}, mesmo que pages > 0."""
        mock_fetch.return_value = {"pages": 3, "documents": {}}
        harvester = _make_harvester()
        results = list(harvester.harvest_documents())

        self.assertEqual(results, [])
        self.assertEqual(mock_fetch.call_count, 1)

    @patch("core.utils.harvesters.fetch_data")
    def test_stops_when_fetch_raises_on_first_page(self, mock_fetch):
        """Quando a primeira página falha, a exceção deve propagar."""
        mock_fetch.side_effect = NonRetryableError("connection error")
        harvester = _make_harvester()

        with self.assertRaises(NonRetryableError):
            list(harvester.harvest_documents())

        self.assertEqual(mock_fetch.call_count, 1)

    @patch("core.utils.harvesters.fetch_data")
    def test_stops_when_fetch_raises_on_middle_page(self, mock_fetch):
        """Quando uma página intermediária falha, a exceção deve propagar."""
        mock_fetch.side_effect = [
            {"pages": 3, "documents": {"pid1": ITEM_JTEST}},
            NonRetryableError("page 2 error"),
        ]
        harvester = _make_harvester()

        with self.assertRaises(NonRetryableError):
            list(harvester.harvest_documents())

    @patch("core.utils.harvesters.fetch_data")
    def test_respects_total_pages_boundary(self, mock_fetch):
        """Não deve requisitar páginas além de total_pages."""
        mock_fetch.return_value = {
            "pages": 1,
            "documents": {"pid1": ITEM_JTEST},
        }
        harvester = _make_harvester()
        list(harvester.harvest_documents())

        self.assertEqual(mock_fetch.call_count, 1)

    @patch("core.utils.harvesters.fetch_data")
    def test_base_url_built_correctly_in_init(self, mock_fetch):
        """base_url deve ser construída no __init__ e reusada nas páginas."""
        mock_fetch.return_value = {"pages": 1, "documents": {"p1": ITEM_JTEST}}
        harvester = _make_harvester(
            domain="www.scielo.br",
            from_date="2024-01-01",
            until_date="2024-12-31",
            limit=50,
        )
        list(harvester.harvest_documents())

        called_url = mock_fetch.call_args[0][0]
        self.assertIn("begin_date=2024-01-01", called_url)
        self.assertIn("end_date=2024-12-31", called_url)
        self.assertIn("limit=50", called_url)
        self.assertIn("page=1", called_url)


# ---------------------------------------------------------------------------
# format_normalized
# ---------------------------------------------------------------------------

class FormatNormalizedTest(TestCase):
    """Testa format_normalized: deve produzir o dicionário completo e tipado."""

    def setUp(self):
        self.harvester = _make_harvester()

    def test_fields_are_present(self):
        doc = self.harvester.format_normalized("abc123", ITEM_JTEST)
        for field in ("pid_v1", "pid_v2", "pid_v3", "collection_acron",
                      "journal_acron", "publication_date", "publication_year",
                      "url", "source_type", "origin_date", "metadata"):
            self.assertIn(field, doc)

    def test_pid_v3_is_set(self):
        doc = self.harvester.format_normalized("abc123", ITEM_JTEST)
        self.assertEqual(doc["pid_v3"], "abc123")

    def test_publication_year_extracted(self):
        doc = self.harvester.format_normalized("abc123", ITEM_JTEST)
        self.assertEqual(doc["publication_year"], "2024")

    def test_publication_year_none_when_date_short(self):
        item = {**ITEM_JTEST, "publication_date": "20"}
        doc = self.harvester.format_normalized("abc123", item)
        self.assertIsNone(doc["publication_year"])

    def test_xml_url_contains_pid_and_acron(self):
        doc = self.harvester.format_normalized("abc123", ITEM_JTEST)
        self.assertIn("jtest", doc["url"])
        self.assertIn("abc123", doc["url"])
        self.assertIn("format=xml", doc["url"])

    def test_xml_url_is_none_when_journal_acron_missing(self):
        item = {**ITEM_JTEST, "journal_acronym": None}
        doc = self.harvester.format_normalized("abc123", item)
        self.assertIsNone(doc["url"])

    def test_xml_url_is_none_when_pid_v3_missing(self):
        doc = self.harvester.format_normalized(None, ITEM_JTEST)
        self.assertIsNone(doc["url"])

    def test_source_type_is_opac(self):
        doc = self.harvester.format_normalized("abc123", ITEM_JTEST)
        self.assertEqual(doc["source_type"], "opac")

    def test_collection_acron_from_harvester(self):
        doc = self.harvester.format_normalized("abc123", ITEM_JTEST)
        self.assertEqual(doc["collection_acron"], "scl")

    def test_origin_date_uses_update_when_present(self):
        doc = self.harvester.format_normalized("abc123", ITEM_JTEST)
        # update="Tue, 16 Jan 2024 12:00:00 GMT" → "2024-01-16"
        self.assertEqual(doc["origin_date"], "2024-01-16")

    def test_origin_date_falls_back_to_create(self):
        item = {**ITEM_JTEST, "update": None}
        doc = self.harvester.format_normalized("abc123", item)
        # create="Mon, 15 Jan 2024 10:00:00 GMT" → "2024-01-15"
        self.assertEqual(doc["origin_date"], "2024-01-15")

    def test_origin_date_none_when_both_missing(self):
        item = {**ITEM_JTEST, "update": None, "create": None}
        doc = self.harvester.format_normalized("abc123", item)
        self.assertIsNone(doc["origin_date"])

    def test_metadata_keys(self):
        doc = self.harvester.format_normalized("abc123", ITEM_JTEST)
        for key in ("aop_pid", "default_language", "created_at", "updated_at",
                    "raw_data", "harvested_at"):
            self.assertIn(key, doc["metadata"])

    def test_metadata_raw_data_is_original_item(self):
        doc = self.harvester.format_normalized("abc123", ITEM_JTEST)
        self.assertEqual(doc["metadata"]["raw_data"], ITEM_JTEST)


# ---------------------------------------------------------------------------
# format_raw
# ---------------------------------------------------------------------------

class FormatRawTest(TestCase):
    """Testa format_raw: retorna estrutura mínima com item bruto."""

    def setUp(self):
        self.harvester = _make_harvester()

    def test_fields_are_present(self):
        raw = self.harvester.format_raw("abc123", ITEM_JTEST)
        for field in ("pid_v3", "url", "origin_date", "collection_acron", "item"):
            self.assertIn(field, raw)

    def test_item_is_original(self):
        raw = self.harvester.format_raw("abc123", ITEM_JTEST)
        self.assertEqual(raw["item"], ITEM_JTEST)

    def test_pid_v3_is_set(self):
        raw = self.harvester.format_raw("abc123", ITEM_JTEST)
        self.assertEqual(raw["pid_v3"], "abc123")

    def test_url_contains_pid_and_acron(self):
        raw = self.harvester.format_raw("abc123", ITEM_JTEST)
        self.assertIn("jtest", raw["url"])
        self.assertIn("abc123", raw["url"])


# ---------------------------------------------------------------------------
# _parse_gmt_date
# ---------------------------------------------------------------------------

class ParseGmtDateTest(TestCase):

    def setUp(self):
        self.harvester = _make_harvester()

    def test_valid_gmt_date(self):
        result = self.harvester._parse_gmt_date("Mon, 15 Jan 2024 10:00:00 GMT")
        self.assertEqual(result, "2024-01-15")

    def test_returns_none_for_none_input(self):
        self.assertIsNone(self.harvester._parse_gmt_date(None))

    def test_returns_none_for_empty_string(self):
        self.assertIsNone(self.harvester._parse_gmt_date(""))

    def test_returns_none_for_invalid_format(self):
        self.assertIsNone(self.harvester._parse_gmt_date("2024-01-15"))