"""
Tests for string utility functions.
"""
import pytest

from core.utils.string_utils import sanitize_unicode_surrogates


class TestSanitizeUnicodeSurrogates:
    """Tests for the sanitize_unicode_surrogates function."""

    def test_sanitize_simple_string_with_surrogates(self):
        """Test that surrogate characters in strings are replaced."""
        # String with a low surrogate (would be from 'Sumário' read with encoding errors)
        input_str = "Sum\udce1rio.pdf"
        result = sanitize_unicode_surrogates(input_str)
        
        # Surrogates should be replaced with replacement character
        assert "\udce1" not in result
        assert "Sum" in result
        assert "rio.pdf" in result
        # Should contain replacement character or be properly encoded
        assert result in ["Sum�rio.pdf", "Sumário.pdf", "Sum\ufffdrio.pdf"]

    def test_sanitize_string_without_surrogates(self):
        """Test that normal strings pass through unchanged."""
        input_str = "normal_file.pdf"
        result = sanitize_unicode_surrogates(input_str)
        assert result == input_str

    def test_sanitize_dict_with_surrogate_in_value(self):
        """Test that surrogates in dict values are sanitized."""
        input_dict = {
            "file": "Sum\udce1rio.pdf",
            "count": 5,
            "status": "ok"
        }
        result = sanitize_unicode_surrogates(input_dict)
        
        assert isinstance(result, dict)
        assert result["count"] == 5
        assert result["status"] == "ok"
        assert "\udce1" not in result["file"]

    def test_sanitize_dict_with_surrogate_in_key(self):
        """Test that surrogates in dict keys are sanitized."""
        input_dict = {
            "Sum\udce1rio": "value"
        }
        result = sanitize_unicode_surrogates(input_dict)
        
        assert isinstance(result, dict)
        # The key should be sanitized
        for key in result.keys():
            assert "\udce1" not in key

    def test_sanitize_list_with_surrogates(self):
        """Test that surrogates in lists are sanitized."""
        input_list = [
            "normal.pdf",
            "Sum\udce1rio.pdf",
            {"file": "test\udce1.txt"}
        ]
        result = sanitize_unicode_surrogates(input_list)
        
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0] == "normal.pdf"
        assert "\udce1" not in result[1]
        assert "\udce1" not in result[2]["file"]

    def test_sanitize_nested_structure(self):
        """Test that deeply nested structures are sanitized."""
        input_data = {
            "exceptions": [
                {
                    "file": "Sum\udce1rio.pdf",
                    "error": "Some error",
                    "nested": {
                        "path": "/path/to/\udce1file"
                    }
                }
            ],
            "count": 1
        }
        result = sanitize_unicode_surrogates(input_data)
        
        assert isinstance(result, dict)
        assert "\udce1" not in result["exceptions"][0]["file"]
        assert "\udce1" not in result["exceptions"][0]["nested"]["path"]
        assert result["count"] == 1

    def test_sanitize_tuple(self):
        """Test that tuples are properly handled."""
        input_tuple = ("normal", "test\udce1")
        result = sanitize_unicode_surrogates(input_tuple)
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] == "normal"
        assert "\udce1" not in result[1]

    def test_sanitize_set(self):
        """Test that sets are properly handled."""
        input_set = {"normal", "test\udce1"}
        result = sanitize_unicode_surrogates(input_set)
        
        assert isinstance(result, set)
        assert "normal" in result
        # Check that no item has surrogates
        for item in result:
            assert "\udce1" not in item

    def test_sanitize_non_string_types(self):
        """Test that non-string types pass through unchanged."""
        assert sanitize_unicode_surrogates(42) == 42
        assert sanitize_unicode_surrogates(3.14) == 3.14
        assert sanitize_unicode_surrogates(True) is True
        assert sanitize_unicode_surrogates(None) is None

    def test_sanitize_empty_structures(self):
        """Test that empty structures are handled correctly."""
        assert sanitize_unicode_surrogates({}) == {}
        assert sanitize_unicode_surrogates([]) == []
        assert sanitize_unicode_surrogates("") == ""

    def test_sanitize_real_world_failure_case(self):
        """Test the actual failure case from the issue."""
        # Simulating the failures dict that caused the original error
        failures = [
            {
                "file": "/scielo_www/pepsic/bases/pdf/vinculo/v9n2/Sum\udce1rio.pdf",
                "error": "Some error message"
            }
        ]
        detail = {
            "migrated": 10,
            "failures": failures
        }
        
        result = sanitize_unicode_surrogates(detail)
        
        # Should not contain surrogates
        assert "\udce1" not in str(result)
        assert result["migrated"] == 10
        assert isinstance(result["failures"], list)
        assert len(result["failures"]) == 1
        assert "\udce1" not in result["failures"][0]["file"]
