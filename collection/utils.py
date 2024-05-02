import re
import logging
from iso639 import Lang
from iso639.exceptions import InvalidLanguageValue

def language_iso(code):
    code = re.split(r"-|_", code)[0] if code else ""
    try:
        return Lang(code).pt1
    except InvalidLanguageValue as e:
        logging.error(f"{e.msg} ({code})")
        return ''