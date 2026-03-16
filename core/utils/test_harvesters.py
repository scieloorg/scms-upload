from unittest import TestCase
from unittest.mock import patch

from core.utils.harvesters import OPACHarvester
from core.utils.requester import NonRetryableError


class OPACHarvesterTest(TestCase):
    """Tests for OPACHarvester.harvest_documents error handling."""

    def _make_harvester(self, **kwargs):
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

    @patch("core.utils.harvesters.fetch_data")
    def test_harvest_documents_stops_when_first_page_fails(self, mock_fetch):
        """When the first page (total_pages unknown) fails, harvesting stops."""
        mock_fetch.side_effect = NonRetryableError("Invalid JSON response")

        harvester = self._make_harvester()
        documents = list(harvester.harvest_documents())

        self.assertEqual(documents, [])
        self.assertEqual(mock_fetch.call_count, 1)

    @patch("core.utils.harvesters.fetch_data")
    def test_harvest_documents_skips_failing_page_when_total_pages_known(
        self, mock_fetch
    ):
        """When total_pages is known and a middle page fails, harvesting continues."""
        page1_response = {
            "pages": 3,
            "documents": {
                "abc123": {
                    "journal_acronym": "jtest",
                    "pid_v2": "S0001-00002024000100001",
                    "publication_date": "2024-01-01",
                },
            },
        }
        page3_response = {
            "pages": 3,
            "documents": {
                "def456": {
                    "journal_acronym": "jtest",
                    "pid_v2": "S0001-00002024000100002",
                    "publication_date": "2024-06-01",
                },
            },
        }
        mock_fetch.side_effect = [
            page1_response,
            NonRetryableError("page 2 error"),
            page3_response,
        ]

        harvester = self._make_harvester()
        documents = list(harvester.harvest_documents())

        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0]["pid_v3"], "abc123")
        self.assertEqual(documents[1]["pid_v3"], "def456")
        self.assertEqual(mock_fetch.call_count, 3)

    @patch("core.utils.harvesters.fetch_data")
    def test_harvest_documents_returns_documents_on_success(self, mock_fetch):
        """Documents are yielded correctly from a successful response."""
        mock_fetch.return_value = {
            "pages": 1,
            "documents": {
                "xyz789": {
                    "journal_acronym": "jtest",
                    "pid_v1": "v1",
                    "pid_v2": "v2",
                    "publication_date": "2024-03-15",
                    "default_language": "en",
                },
            },
        }

        harvester = self._make_harvester()
        documents = list(harvester.harvest_documents())

        self.assertEqual(len(documents), 1)
        doc = documents[0]
        self.assertEqual(doc["pid_v3"], "xyz789")
        self.assertEqual(doc["pid_v1"], "v1")
        self.assertEqual(doc["pid_v2"], "v2")
        self.assertEqual(doc["journal_acron"], "jtest")
        self.assertEqual(doc["collection_acron"], "scl")
        self.assertIn("format=xml", doc["url"])

    @patch("core.utils.harvesters.fetch_data")
    def test_harvest_documents_stops_on_empty_documents(self, mock_fetch):
        """When a page returns no documents, harvesting stops."""
        mock_fetch.return_value = {
            "pages": 3,
            "documents": {},
        }

        harvester = self._make_harvester()
        documents = list(harvester.harvest_documents())

        self.assertEqual(documents, [])
        self.assertEqual(mock_fetch.call_count, 1)

    @patch("core.utils.harvesters.fetch_data")
    def test_harvest_documents_stops_after_last_page_fails(self, mock_fetch):
        """When the error is on the last page, harvesting still stops gracefully."""
        page1_response = {
            "pages": 2,
            "documents": {
                "abc123": {
                    "journal_acronym": "jtest",
                    "publication_date": "2024-01-01",
                },
            },
        }
        mock_fetch.side_effect = [
            page1_response,
            NonRetryableError("last page error"),
        ]

        harvester = self._make_harvester()
        documents = list(harvester.harvest_documents())

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["pid_v3"], "abc123")
