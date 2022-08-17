from unittest.mock import patch
from unittest import TestCase


from libs.dsm.publication.issues import publish_issue, Issue
from libs.dsm.publication.exceptions import IssueDataError


@patch("libs.dsm.publication.db.save_data", return_value=None)
@patch("libs.dsm.publication.issues.get_issue", return_value=Issue())
class TestIssue(TestCase):

    def _get_issue_data(self):
        return {
            "id": "id value",
            "journal_id": "journal_id value",
            "publication": {
                 "months": {"start": 1, "end": 3},
            },
            "issue_pid": "issue_pid value",
            "issue_order": "issue_order value",
            "label": "label value",
            "year": "year value",
            "volume": "volume value",
            "number": "number value",
            "supplement": "supplement value",
            "type": "type value",
        }

    def setUp(self):
        self.issue_data = self._get_issue_data()

    def test_publication_date_months_end_is_missing(self, mock_get_issue, mock_save):
        del self.issue_data["publication_date"]["months"]["end"]
        with self.assertRaises(IssueDataError) as exc:
            publish_issue(self.issue_data)
        self.assertIn("end", str(exc.exception))

    def test_publication_date_months_start_is_missing(self, mock_get_issue, mock_save):
        del self.issue_data["publication_date"]["months"]["end"]
        with self.assertRaises(IssueDataError) as exc:
            publish_issue(self.issue_data)
        self.assertIn("start", str(exc.exception))

    def test_id_is_missing(self, mock_get_issue, mock_save):
        del self.issue_data["id"]
        with self.assertRaises(IssueDataError) as exc:
            publish_issue(self.issue_data)
        self.assertIn("id", str(exc.exception))

    def test_issue_order_is_missing(self, mock_get_issue, mock_save):
        del self.issue_data["issue_order"]
        with self.assertRaises(IssueDataError) as exc:
            publish_issue(self.issue_data)
        self.assertIn("issue_order", str(exc.exception))

    def test_issue_pid_is_missing(self, mock_get_issue, mock_save):
        del self.issue_data["issue_pid"]
        with self.assertRaises(IssueDataError) as exc:
            publish_issue(self.issue_data)
        self.assertIn("issue_pid", str(exc.exception))

    def test_journal_id_is_missing(self, mock_get_issue, mock_save):
        del self.issue_data["journal_id"]
        with self.assertRaises(IssueDataError) as exc:
            publish_issue(self.issue_data)
        self.assertIn("journal_id", str(exc.exception))

    def test_year_is_missing(self, mock_get_issue, mock_save):
        del self.issue_data["year"]
        with self.assertRaises(IssueDataError) as exc:
            publish_issue(self.issue_data)
        self.assertIn("year", str(exc.exception))
