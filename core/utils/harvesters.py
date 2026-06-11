import logging
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional
from urllib.parse import urlencode

from core.utils.requester import fetch_data


logger = logging.getLogger(__name__)


class OPACHarvester:
    """
    Harvester para coletar documentos do OPAC via endpoint counter_dict.
    """

    def __init__(
        self,
        domain: str = "www.scielo.br",
        collection_acron: str = "scl",
        from_date: Optional[str] = None,
        until_date: Optional[str] = None,
        limit: int = 100,
        timeout: int = 5,
    ):
        """
        Inicializa o harvester do OPAC.

        Args:
            domain: Domínio do OPAC (ex: 'www.scielo.br')
            collection_acron: Acrônimo da coleção (ex: 'scl')
            from_date: Data inicial no formato YYYY-MM-DD
            until_date: Data final no formato YYYY-MM-DD
            limit: Número de documentos por página
            timeout: Timeout em segundos para requisições
        """
        if not domain.startswith("http"):
            domain = f"http://{domain}"
        self.domain = domain

        self.collection_acron = collection_acron
        self.from_date = from_date or "2000-01-01"
        self.until_date = until_date or datetime.now(timezone.utc).isoformat()[:10]
        self.limit = limit
        self.timeout = timeout
        self.base_url = (
            f"{self.domain}/api/v1/counter_dict?"
            f"end_date={self.until_date}&begin_date={self.from_date}"
            f"&limit={self.limit}"
        )

    def harvest_documents(self) -> Generator[Dict[str, Any], None, None]:
        """
        Função geradora que retorna documentos do OPAC.

        Yields:
            Dict contendo:
                - pid_v1: Identificador PID v1
                - pid_v2: Identificador PID v2
                - pid_v3: Identificador PID v3
                - collection_acron: Acrônimo da coleção
                - journal_acron: Acrônimo do periódico
                - publication_date: Data de publicação
                - publication_year: Ano de publicação
                - url: URL para obter o XML completo
                - source_type: 'opac'
                - origin_date: Data de origem
                - metadata: Metadados adicionais do documento
        """
        page = 1
        total_pages = 0

        while True:
            # Constrói URL
            url = f"{self.base_url}&page={page}"

            logger.info(f"Fetching OPAC documents from: {url}")
            response = fetch_data(url, json=True, timeout=self.timeout)

            total_pages = total_pages or response.get("pages") or 0
            if not total_pages:
                break
            
            documents = response.get("documents", {})
            if not documents:
                break

            yield from documents.items()

            page += 1
            if total_pages and page > total_pages:
                logger.info(f"Finish to process {total_pages}")
                break

    def format_raw(self, pid_v3, item):
        journal_acron = item.get("journal_acronym")
        xml_url = f"{self.domain}/j/{journal_acron}/a/{pid_v3}/?format=xml"
        origin_date = self._parse_gmt_date(
            item.get("update") or item.get("create")
        )
        return {
            "pid_v3": pid_v3,
            "url": xml_url,
            "origin_date": origin_date,
            "collection_acron": self.collection_acron,
            "item": item,
        }

    def format_normalized(self, pid_v3, item):
        journal_acron = item.get("journal_acronym")
        
        xml_url = None
        if journal_acron and pid_v3:
            xml_url = f"{self.domain}/j/{journal_acron}/a/{pid_v3}/?format=xml"

        origin_date = self._parse_gmt_date(
            item.get("update") or item.get("create")
        )
        pub_date = item.get("publication_date", "")
        publication_year = pub_date[:4] if len(pub_date) >= 4 else None
        return {
            "pid_v1": item.get("pid_v1"),
            "pid_v2": item.get("pid_v2"),
            "pid_v3": pid_v3,
            "collection_acron": self.collection_acron,
            "journal_acron": journal_acron,
            "publication_date": pub_date,
            "publication_year": publication_year,
            "url": xml_url,
            "source_type": "opac",
            "origin_date": origin_date,
            "metadata": {
                "aop_pid": item.get("aop_pid"),
                "default_language": item.get("default_language"),
                "created_at": self._parse_gmt_date(item.get("create")),
                "updated_at": self._parse_gmt_date(item.get("update")),
                "raw_data": item,
                "harvested_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    def _parse_gmt_date(self, date_str: Optional[str]) -> Optional[str]:
        """
        Converte data GMT para formato ISO.

        Args:
            date_str: String de data no formato GMT (ex: "Sat, 28 Nov 2020 23:42:43 GMT")

        Returns:
            Data no formato ISO (YYYY-MM-DD) ou None se falhar
        """
        if not date_str:
            return None

        try:
            dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z")
            return dt.isoformat()[:10]
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse GMT date '{date_str}': {e}")
            return None
