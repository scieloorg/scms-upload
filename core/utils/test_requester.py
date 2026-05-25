from unittest import TestCase
from unittest.mock import Mock, patch

from core.utils.requester import NonRetryableError, fetch_data


class FetchDataJsonDecodeErrorTest(TestCase):
    """Tests for fetch_data handling of invalid JSON responses."""

    @patch("core.utils.requester.requests.get")
    def test_fetch_data_raises_non_retryable_error_on_empty_json_response(
        self, mock_get
    ):
        """When json=True and response body is empty, fetch_data should raise
        NonRetryableError instead of letting JSONDecodeError propagate."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b""
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = ValueError(
            "Expecting value: line 1 column 1 (char 0)"
        )
        mock_get.return_value = mock_response

        with self.assertRaises(NonRetryableError):
            fetch_data("https://example.com/api", json=True)

    @patch("core.utils.requester.requests.get")
    def test_fetch_data_raises_non_retryable_error_on_html_json_response(
        self, mock_get
    ):
        """When json=True and response body is HTML, fetch_data should raise
        NonRetryableError."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"<html>Not Found</html>"
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = ValueError("Expecting value")
        mock_get.return_value = mock_response

        with self.assertRaises(NonRetryableError) as ctx:
            fetch_data("https://example.com/api", json=True)

        self.assertIn("Invalid JSON response", str(ctx.exception))

    @patch("core.utils.requester.requests.get")
    def test_fetch_data_returns_json_on_valid_response(self, mock_get):
        """When json=True and response body is valid JSON, return parsed dict."""
        expected = {"documents": {}, "pages": 1}
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = expected
        mock_get.return_value = mock_response

        result = fetch_data("https://example.com/api", json=True)

        self.assertEqual(result, expected)

    @patch("core.utils.requester.requests.get")
    def test_fetch_data_returns_content_when_json_false(self, mock_get):
        """When json=False, return raw response content."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"raw content"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = fetch_data("https://example.com/api", json=False)

        self.assertEqual(result, b"raw content")
