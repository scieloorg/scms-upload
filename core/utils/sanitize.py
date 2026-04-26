import json


def sanitize_for_json(obj):
    """Recursively sanitize data to make it JSON-serializable.

    Handles:
    - Unicode surrogate characters (U+D800-U+DFFF), which are invalid in JSON
      and rejected by PostgreSQL.  They can appear in file paths read from
      filesystems using Python's 'surrogateescape' error handler.
    - Django lazy translation objects (``__proxy__``) and any other
      non-JSON-serializable types, which are converted to their string
      representation.
    """
    if isinstance(obj, str):
        # Encode using surrogateescape to recover original bytes from surrogates,
        # then decode as UTF-8 replacing any invalid sequences.
        # Fall back to surrogatepass for surrogates outside the DC80-DCFF range.
        try:
            return obj.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
        except UnicodeEncodeError:
            return obj.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
    if isinstance(obj, dict):
        return {sanitize_for_json(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(item) for item in obj]
    # For any other type, test JSON serializability directly.  If the object
    # serializes fine (int, float, bool, None, …) return it unchanged.
    # Otherwise convert to string and re-sanitize to also catch surrogate code
    # points that __str__() might produce (e.g. Django lazy __proxy__).
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return sanitize_for_json(str(obj))
