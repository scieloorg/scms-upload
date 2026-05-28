"""
Verifica a presença exata de metadados de artigo em um texto.
"""
import logging
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
        return {"content": content}
    except Exception as e:
        return {"error": str(e), "function": "check_url"}
    

def clean_pdf_text(raw):
    """
    Limpa texto extraído de PDF para maximizar a chance de match
    com metadados do artigo.
    """
    text = raw

    # 1. Decodifica entidades HTML residuais (alguns extratores deixam)
    text = unescape(text)

    # 2. Remove hifenização de fim de linha: "publi-\ncação" → "publicação"
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)

    # 3. Substitui quebras de linha por espaço
    text = text.replace("\n", " ").replace("\r", " ")

    # 4. Remove caracteres de controle (form feed, etc.)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)

    # 5. Colapsa espaços múltiplos
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def check_content(article_metadata, content, format):
    try:
        if not article_metadata:
            raise ValueError("check_content: Article metadata is required for availability check.")
        if not content:
            raise ValueError("check_content: Content is required for availability check.")
        try:
            if format == "pdf":
                # Decodifica bytes → str
                if isinstance(content, bytes):
                    content = content.decode("utf-8", errors="replace")
                    if not content:
                        raise ValueError("check_content: Unable to decode content for pdf")
                logging.exception("check content 1111")

                # Limpeza adequada para texto vindo de PDF
                content = clean_pdf_text(content)
                if not content:
                    raise ValueError("check_content: Unable to clean pdf content")
                logging.exception("check content 2222")
            else:
                content = content.decode("utf-8")
                if not content:
                    raise ValueError("check_content: Unable to decode content")
                
                logging.exception("check content 3333")
                content = " ".join(content.split())
                logging.exception("check content 4444")
                if "PID:" in content:
                    logging.exception("check content 5555")
                    position = content.find("PID:")
                    if position:
                        logging.exception("check content 6666")
                        content = content[:position+1000]
                logging.exception("check content 7777") 
        except (AttributeError, IndexError) as exc:
            logging.exception(f"check content {exc}") 
            pass
        result = check_metadata(article_metadata, content)
        numbers = compute_rate(result)
        logging.info(f"check content: {result}")
        logging.info(f"check content: {numbers}")
        
        response = {}
        response["result"] = result
        response.update(numbers)
        return response
    except Exception as e:
        return {"error": str(e), "type": str(type(e))}


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
    if not text:
        raise ValueError(f"check_metadata: Unable to check metadata because text is not provided")
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
            "total_found": int,
            "total_not_found": int,
            "total": int,
            "rate": float,
        }
    """
    total = len(items)
    total_found = sum(1 for _, _, found in items if found)

    return {
        "total_found": total_found,
        "total_not_found": total - total_found,
        "total": total,
        "rate": total_found / total if total else 0.0,
    }