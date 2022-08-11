from unittest.mock import patch
from unittest import TestCase


from .journals import publish_journal, Journal
from .exceptions import JournalDataError


@patch("libs.dsm.publication.db.save_data", return_value=None)
@patch("libs.dsm.publication.journals.get_journal", return_value=Journal())
class TestJournal(TestCase):

    def _get_journal_data(self):
        return {
            "acronym": "acronym value",
            "contact": {
                 "email": "email value",
                 "address": "address value",
            },
            "issue_count": "issue_count value",
            "mission": [
                {"language": "en", "description": "mission text"},
            ],
            "publisher": {
                 "name": "name value",
                 "city": "city value",
                 "state": "state value",
                 "country": "country value",
            },
            "scielo_issn": "scielo_issn value",
            "short_title": "short_title value",
            "sponsors": ["sponsors value"],
            "status_history": [
                {"status": "en", "since": "date", "reason": "dddd"},
            ],
            "subject_areas": ["subject_areas value"],
            "subject_categories": ["subject_categories value"],
            "title": "title value",
            "title_iso": "title_iso value",
        }

    def setUp(self):
        self.journal_data = self._get_journal_data()

    def test_acronym_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["acronym"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("acronym", str(exc.exception))

    def test_contact_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["contact"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("contact", str(exc.exception))

    def test_contact_email_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["contact"]["email"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("email", str(exc.exception))

    def test_contact_address_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["contact"]["address"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("address", str(exc.exception))

    def test_issue_count_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["issue_count"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("issue_count", str(exc.exception))

    def test_mission_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["mission"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("mission", str(exc.exception))

    def test_publisher_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["publisher"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("publisher", str(exc.exception))

    def test_publisher_name_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["publisher"]["name"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("name", str(exc.exception))

    def test_publisher_city_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["publisher"]["city"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("city", str(exc.exception))

    def test_publisher_state_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["publisher"]["state"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("state", str(exc.exception))

    def test_publisher_country_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["publisher"]["country"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("country", str(exc.exception))

    def test_scielo_issn_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["scielo_issn"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("scielo_issn", str(exc.exception))

    def test_short_title_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["short_title"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("short_title", str(exc.exception))

    def test_sponsors_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["sponsors"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("sponsors", str(exc.exception))

    def test_status_history_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["status_history"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("status_history", str(exc.exception))

    def test_subject_areas_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["subject_areas"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("subject_areas", str(exc.exception))

    def test_subject_categories_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["subject_categories"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("subject_categories", str(exc.exception))

    def test_title_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["title"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("title", str(exc.exception))

    def test_title_iso_is_missing(self, mock_get_journal, mock_save):
        del self.journal_data["title_iso"]
        with self.assertRaises(JournalDataError) as exc:
            publish_journal(self.journal_data)
        self.assertIn("title_iso", str(exc.exception))
