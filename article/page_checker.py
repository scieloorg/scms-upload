"""
Verifica a presença exata de metadados de artigo em um texto.
"""

import re
import unicodedata
from core.utils.requester import fetch_data


def format_url(public_website_url, pid_v3, journal_acron, format, lang_code=None):
    url = f"{public_website_url}/j/{journal_acron}/a/{pid_v3}/"
    if format or lang_code:
        url += "?"
    if format:
        url += f"format={format}"
    if lang_code:
        if format:
            url += "&"
        url += f"lang={lang_code}"
    return url


def format_classic_url(website_url, pid_v2, format, lang_code=None):
    if format == "pdf":
        return f"{website_url}/scielo.php?script=sci_pdf&pid={pid_v2}&tlng={lang_code}"
    return f"{website_url}/scielo.php?script=sci_arttext&pid={pid_v2}&tlng={lang_code}"


def check_url(url, timeout):
    try:
        if not url:
            raise ValueError("check_page_url_and_content: URL is required for availability check.")
        content = fetch_data(url, timeout=timeout or 30)
        if not content:
            raise ValueError("check_page_url_and_content: No content fetched from URL.")
        return {"content": content}
    except Exception as e:
        return {"error": str(e)}
    

def check_content(article_metadata, content):
    try:
        if not article_metadata:
            raise ValueError("check_page_url_and_content: Article metadata is required for availability check.")
        if not content:
            raise ValueError("check_page_url_and_content: Content is required for availability check.")
        try:
            content = content.split("<body", 1)[0]
        except (AttributeError, IndexError):
            pass  # Se não conseguir dividir, continua com o conteúdo original
        result = check_metadata(article_metadata, content)

        numbers = compute_rate(result)
        rate = numbers.get("rate", 0)
        return {
            "result": result,
            "numbers": numbers,
            "rate": rate,
        }
    except Exception as e:
        return {"error": str(e)}


def normalize(text):
    """Normaliza: lowercase, sem acentos, espaços extras colapsados."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def is_found(query, text):
    """
    Verifica se `query` está presente em `text` (busca exata, normalizada).
    """
    return normalize(query) in normalize(text)


def check_metadata(metadata, text):
    """
    Itera os metadados e verifica cada item contra o texto.

    Parameters
    ----------
    metadata : list[tuple]
        Lista de (label, valor).
    text : str

    Returns
    -------
    list[tuple]
        Lista de (label, valor, encontrado).
    """
    return [
        (label, value, is_found(value, text))
        for label, value in metadata
        if value and isinstance(value, str) and value.strip()
    ]


def compute_rate(items):
    """
    Calcula a taxa de itens encontrados.

    Parameters
    ----------
    items : list[tuple]
        Saída de check_metadata: [(label, valor, encontrado), ...]

    Returns
    -------
    dict
        {
            "found_count": int,
            "not_found_count": int,
            "total": int,
            "rate": float,
        }
    """
    total = len(items)
    found_count = sum(1 for _, _, found in items if found)

    return {
        "found_count": found_count,
        "not_found_count": total - found_count,
        "total": total,
        "rate": found_count / total if total else 0.0,
    }
