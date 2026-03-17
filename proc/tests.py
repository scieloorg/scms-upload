import json
import unittest

from core.utils.sanitize import sanitize_for_json


class SanitizeForJsonTest(unittest.TestCase):
    """Tests for sanitize_for_json function that removes surrogate characters."""

    def test_plain_string_unchanged(self):
        self.assertEqual(sanitize_for_json("hello world"), "hello world")

    def test_string_with_surrogate_is_replaced(self):
        # \udce1 is a surrogate escape for byte 0xe1 (Latin-1 'á')
        text = "v4n2 Sum\udce1rio"
        result = sanitize_for_json(text)
        self.assertNotIn("\udce1", result)
        # The surrogate should be replaced with the Unicode replacement character
        self.assertIn("\ufffd", result)

    def test_result_is_valid_json(self):
        detail = {
            "failures": [
                {"file": "/scielo_www/revenf/bases/pdf/ccs/v4n2/v4n2 Sum\udce1rio.pdf"}
            ],
            "migrated": 5,
        }
        result = sanitize_for_json(detail)
        # Must not raise
        json_str = json.dumps(result)
        self.assertIn("Sum", json_str)

    def test_dict_with_surrogates_in_keys_and_values(self):
        data = {"\udce1key": "val\udce1ue"}
        result = sanitize_for_json(data)
        json_str = json.dumps(result)
        self.assertNotIn("\\udce1", json_str)

    def test_nested_list_with_surrogates(self):
        data = [["Sum\udce1rio", "normal"], "ok\udce9"]
        result = sanitize_for_json(data)
        json_str = json.dumps(result)
        self.assertNotIn("\\udce1", json_str)
        self.assertNotIn("\\udce9", json_str)

    def test_non_string_values_preserved(self):
        data = {"count": 42, "flag": True, "empty": None}
        result = sanitize_for_json(data)
        self.assertEqual(result, data)

    def test_empty_dict(self):
        self.assertEqual(sanitize_for_json({}), {})

    def test_empty_string(self):
        self.assertEqual(sanitize_for_json(""), "")

    def test_normal_unicode_preserved(self):
        # Normal accented characters should be preserved
        text = "Sumário"
        self.assertEqual(sanitize_for_json(text), "Sumário")

    def test_multiple_surrogates_in_same_string(self):
        text = "\udce1\udce9\udcf3"
        result = sanitize_for_json(text)
        # All surrogates should be handled
        json.dumps(result)  # Must not raise

    def test_tuple_converted_to_list(self):
        data = ("a\udce1", "b")
        result = sanitize_for_json(data)
        self.assertIsInstance(result, list)
        json.dumps(result)  # Must not raise

    def test_complex_detail_dict_from_real_error(self):
        """Simulate the actual error scenario from the issue."""
        detail = {
            "failures": [
                {
                    "file": "/scielo_www/revenf/bases/pdf/ccs/v4n2/v4n2 Sum\udce1rio.pdf",
                    "error": "some error",
                    "type": "<class 'Exception'>",
                }
            ],
            "migrated": 3,
        }
        result = sanitize_for_json(detail)
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["migrated"], 3)
        self.assertEqual(len(parsed["failures"]), 1)
        self.assertIn("Sum", parsed["failures"][0]["file"])


if __name__ == "__main__":
    unittest.main()
