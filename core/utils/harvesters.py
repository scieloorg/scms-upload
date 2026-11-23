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
        journal_acron: Optional[str] = None,
    ):
        """
        Inicializa o harvester do OPAC.

        Args:
            domain: Domínio do OPAC (ex: 'www.scielo.br')
            collection_acron: Acrônimo da coleção (ex: 'scl')
            from_date: Data inicial em formato ISO 8601
                (ex: '2024-01-31' ou '2024-01-31T10:30:15')
            until_date: Data final em formato ISO 8601
                (ex: '2024-01-31' ou '2024-01-31T10:30:15')
            limit: Número de documentos por página
            timeout: Timeout em segundos para requisições
            journal_acron: Acrônimo do periódico para filtrar (ex: 'rsp')
        """
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        self.domain = domain

        self.collection_acron = collection_acron
        self.from_date = from_date or "2000-01-01"
        self.until_date = until_date or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        self.limit = limit
        self.timeout = timeout
        params = {
            "end_date": self.until_date,
            "begin_date": self.from_date,
            "limit": self.limit,
        }
        if journal_acron:
            params["journal"] = journal_acron
        # urlencode é necessário para preservar o "+" de fusos horários ISO 8601
        self.base_url = f"{self.domain}/api/v2/counter_dict?{urlencode(params)}"

    def harvest_documents(self) -> Generator[Dict[str, Any], None, None]:
        """
        Função geradora que retorna documentos do OPAC.

        Yields:
            Tuplas (aid, item), onde aid é o identificador do artigo no OPAC
            (PID v3) e item é o documento bruto retornado pela API v2.

        Itens formatados por format_normalized contêm:
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
            
            documents = response.get("documents") or []
            if not documents:
                break

            for item in documents:
                yield item.get("aid") or item.get("pid_v3"), item

            page += 1
            if total_pages and page > total_pages:
                logger.info(f"Finish to process {total_pages}")
                break

    def format_raw(self, pid_v3, item):
        journal_acron = item.get("journal_acronym")
        xml_url = f"{self.domain}/j/{journal_acron}/a/{pid_v3}/?format=xml"
        # data e hora completas da atualização na fonte (ArticleSource.source_date)
        source_date = item.get("updated") or item.get("created")
        origin_date = self._parse_iso_date(source_date)
        # v2: is_public; v1: status
        is_public = item["is_public"] if "is_public" in item else item.get("status")
        return {
            "pid_v3": pid_v3,
            "url": xml_url,
            "origin_date": origin_date,
            "source_date": source_date if origin_date else None,
            "collection_acron": self.collection_acron,
            "item": item,
            "is_public": is_public is True or is_public == "true",
        }

    def format_normalized(self, pid_v3, item):
        journal_acron = item.get("journal_acronym")
        
        xml_url = None
        if journal_acron and pid_v3:
            xml_url = f"{self.domain}/j/{journal_acron}/a/{pid_v3}/?format=xml"

        origin_date = self._parse_iso_date(
            item.get("updated") or item.get("created")
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
                "created_at": self._parse_iso_date(item.get("created")),
                "updated_at": self._parse_iso_date(item.get("updated")),
                "raw_data": item,
                "harvested_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    def _parse_iso_date(self, date_str: Optional[str]) -> Optional[str]:
        """
        Converte data ISO 8601 para formato YYYY-MM-DD.

        Args:
            date_str: String de data em formato ISO 8601
                (ex: "2024-01-31T10:01:00")

        Returns:
            Data no formato ISO (YYYY-MM-DD) ou None se falhar
        """
        if not date_str:
            return None

        try:
            return datetime.fromisoformat(date_str).date().isoformat()
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse ISO date '{date_str}': {e}")
            return None
