"""
String utility functions for handling encoding issues and sanitization.
"""


def sanitize_unicode_surrogates(obj):
    """
    Recursively sanitize Unicode surrogate characters from strings in nested data structures.

    Unicode surrogates (U+D800 to U+DFFF) are invalid in JSON and PostgreSQL.
    They can appear when reading filenames with encoding issues using the 'surrogateescape' error handler.

    This function replaces surrogates with the Unicode replacement character (U+FFFD '�').

    Args:
        obj: Any object (str, dict, list, or other types)

    Returns:
        The sanitized object with surrogates replaced

    Examples:
        >>> sanitize_unicode_surrogates("Sum\\udce1rio.pdf")
        'Sum�rio.pdf'
        >>> sanitize_unicode_surrogates({"file": "Sum\\udce1rio.pdf", "count": 5})
        {'file': 'Sum�rio.pdf', 'count': 5}
    """
    if isinstance(obj, str):
        # Replace surrogates by encoding with 'replace' error handler
        # This replaces invalid surrogates with the replacement character �
        try:
            # First try to encode to UTF-8, which will fail on surrogates
            # Then decode back with 'replace' to handle the surrogates
            return obj.encode("utf-8", errors="replace").decode(
                "utf-8", errors="replace"
            )
        except (UnicodeDecodeError, UnicodeEncodeError):
            # If all else fails, return a string representation
            return repr(obj)
    elif isinstance(obj, dict):
        return {
            sanitize_unicode_surrogates(k): sanitize_unicode_surrogates(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, (list, tuple)):
        result = [sanitize_unicode_surrogates(item) for item in obj]
        return type(obj)(result)
    elif isinstance(obj, set):
        return {sanitize_unicode_surrogates(item) for item in obj}
    else:
        # For other types (int, float, bool, None, etc.), return as-is
        return obj
