import re

from langcodes import standardize_tag, tag_is_valid


def language_iso(code):
    code = re.split(r"-|_", code)[0] if code else ""
    if tag_is_valid(code):
        return standardize_tag(code)
    return ""
