def sanitize_for_json(obj):
    """Recursively sanitize data to remove Unicode surrogate characters.

    Surrogate characters (U+D800-U+DFFF) are invalid in JSON and rejected by
    PostgreSQL.  They can appear in file paths read from filesystems using
    Python's 'surrogateescape' error handler.
    """
    if isinstance(obj, str):
        # Encode using surrogateescape to recover original bytes from surrogates,
        # then decode as UTF-8 replacing any invalid sequences
        return obj.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    if isinstance(obj, dict):
        return {sanitize_for_json(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(item) for item in obj]
    return obj
