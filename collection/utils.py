import re

from langcodes import standardize_tag, tag_is_valid
from langdetect import detect


def language_iso(code):
    """
    Normaliza código de idioma para ISO 639.
    
    Args:
        code: Código do idioma (ex: 'pt-BR', 'en_US')
    
    Returns:
        Código ISO válido ou string vazia
    """
    if not code:
        return ""
    
    # Extrai código base
    base = re.split(r"[-_]", code)[0].lower()
    
    if tag_is_valid(base):
        return standardize_tag(base).split('-')[0]
    
    return ""


def detect_language(text):
    """
    Detecta o idioma de um texto.
    
    Args:
        text: Texto para análise
    
    Returns:
        Código ISO do idioma detectado ou string vazia
    """
    if not text or len(text.strip()) < 10:
        return ""
    
    try:
        return detect(text)
    except:
        return ""


def get_valid_language_code(code2, text_to_detect_language=None):
    valid = language_iso(code2)
    if valid:
        return valid
    if text_to_detect_language:
        return detect_language(text_to_detect_language)
    return None

