"""
Verifica a presença exata de metadados de artigo em um texto.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from html import unescape

from core.utils.requester import fetch_data


# Threshold de similaridade para considerar "encontrado"
SIMILARITY_THRESHOLD = 0.85


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
        return {"content": content.decode("utf-8")}
    except Exception as e:
        return {"error": str(e)}
    

def check_content(article_metadata, content):
    try:
        if not article_metadata:
            raise ValueError("check_page_url_and_content: Article metadata is required for availability check.")
        if not content:
            raise ValueError("check_page_url_and_content: Content is required for availability check.")
        try:
            content = " ".join(content.split())
            position = content.find("PID:")
            if position:
                content = content[:position+1000]
        except (AttributeError, IndexError):
            pass
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
    """Normaliza: decodifica entidades HTML, lowercase, sem acentos, espaços extras colapsados."""
    text = unescape(text)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def similarity(a, b):
    """Retorna a razão de similaridade entre duas strings normalizadas (0.0 a 1.0)."""
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def is_found(query, text, threshold=SIMILARITY_THRESHOLD):
    """
    Verifica se `query` está presente em `text`.

    Primeiro tenta busca exata (substring) no texto normalizado.
    Se não encontrar, tenta similaridade contra trechos do texto
    de tamanho compatível com o query.

    Parameters
    ----------
    query : str
    text : str
    threshold : float
        Mínimo de similaridade para considerar encontrado (0.0 a 1.0).

    Returns
    -------
    bool
    """
    nq = normalize(query)
    nt = normalize(text)

    # Busca exata (substring) — rápida, cobre a maioria dos casos
    if nq in nt:
        return True

    # Para queries curtos (ex: pid_v2, autor sobrenome), substring basta.
    # Similaridade por janela só faz sentido para queries mais longos (títulos).
    if len(nq) < 15:
        return False

    # Busca por similaridade em janelas deslizantes do tamanho do query
    window = len(nq)
    best = 0.0
    # Passo de 1 caractere seria preciso mas lento; usa passo proporcional
    step = max(1, window // 4)
    for i in range(0, len(nt) - window + 1, step):
        chunk = nt[i : i + window]
        ratio = SequenceMatcher(None, nq, chunk).ratio()
        if ratio >= threshold:
            return True
        if ratio > best:
            best = ratio

    return False


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