from functools import cached_property

from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.utils.similarity import how_similar
from pid_provider import exceptions


def compare(registered_items, input_data):
    """
    """
    total_score = 0
    items = []
    for label, registered_item in registered_items.items():
        result = compare_items(label, registered_item, input_data.get(label))
        items.append(result)
        total_score += result["score"]
    return {
        "items": items,
        "total_score": total_score,
        "percentual_score": total_score / len(items)
    }


def compare_lists(registered, xml_adapter_titles):
    if xml_adapter_titles == registered:
        return 1
    if not xml_adapter_titles:
        return 0
    if not registered:
        return 0
    words1 = set()
    for item in xml_adapter_titles:
        words1.update(item.split())
    words2 = set()
    for item in registered:
        words2.update(item.split())
    return how_similar(" ".join(sorted(words1)), " ".join(sorted(words2)))


def compare_items(label, registered, input_data):
    if isinstance(registered, list):
        score = compare_lists(registered, input_data)
    elif (input_data or None) == (registered or None):
        score = 1
    else:
        score = how_similar(input_data, registered)
    response = {"label": label, "score": score}
    if score != 1:
        response["registered"] = registered
    return response


def get_score(registered, xml_data, min_value, max_value):
    if registered == xml_data:
        if registered:
            return max_value
        return min_value
    return 0


def zero_to_none(data):
    if not data:
        return
    if not data.isdigit():
        return data
    if int(data) == 0:
        return None
    return data

class QueryBuilderPidProviderXML:
    """
    Construtor de queries para busca de PidProviderXML.
    
    Centraliza toda a lógica de construção de queries complexas
    para buscar documentos por múltiplos critérios.
    """
    
    def __init__(self, xml_adapter):
        """
        Inicializa o construtor de queries obtendo os dicionários de dados do adaptador.
        
        Parameters
        ----------
        xml_adapter : PidProviderXMLAdapter
            Adaptador com dados do XML para busca
        """
        self.xml_adapter = xml_adapter
        # Centraliza o acesso aos dados brutos e normalizados (hashes de 64 chars)
        self.adapter_data = xml_adapter.data
        self.compare_data = xml_adapter.get_data_to_compare()

    @property
    def pkg_name_list(self):
        # --- Resolução Consolidada de Package Names ---
        pkg_names = set()

        # 1. Nome enviado originalmente via parâmetro no construtor
        if self.xml_adapter.pkg_name:
            pkg_names.add(self.xml_adapter.pkg_name)

        # 2. Nome oficial atual gerado pelo motor de cálculo do XML
        if self.xml_adapter.sps_pkg_name:
            pkg_names.add(self.xml_adapter.sps_pkg_name)

        # 3. Consolida todas as listas de nomes depreciados/alternativos
        pkg_names.update(self.xml_adapter.xml_with_pre.deprecated_sps_pkg_name_list)

        return set(item for item in pkg_names if item)
    
    @cached_property
    def v3(self):
        """PID v3 do documento."""
        return self.xml_adapter.v3
    
    @cached_property
    def v2(self):
        """PID v2 do documento."""
        return self.xml_adapter.v2
    
    @cached_property
    def aop_pid(self):
        """PID AOP (Ahead of Print) do documento."""
        return self.xml_adapter.aop_pid
    
    @cached_property
    def pkg_name(self):
        """Nome do pacote do documento, parâmtro usado ao instanciar XMLAdapter"""
        return self.xml_adapter.pkg_name

    @cached_property
    def sps_pkg_name(self):
        """Nome do pacote do documento (deprecated)."""
        return self.xml_adapter.sps_pkg_name

    @cached_property
    def deprecated_sps_pkg_name(self):
        """Nome do pacote do documento (deprecated)."""
        return self.xml_adapter.sps_pkg_name

    @cached_property
    def main_doi(self):
        """DOI principal do documento."""
        return self.xml_adapter.main_doi
    
    @cached_property
    def journal_issn_electronic(self):
        """ISSN eletrônico do periódico."""
        return self.xml_adapter.journal_issn_electronic
    
    @cached_property
    def journal_issn_print(self):
        """ISSN impresso do periódico."""
        return self.xml_adapter.journal_issn_print
    
    @cached_property
    def elocation_id(self):
        """Identificador de localização eletrônica."""
        return self.xml_adapter.elocation_id
    
    @cached_property
    def fpage(self):
        """Primeira página do artigo."""
        return self.xml_adapter.fpage
    
    @cached_property
    def fpage_seq(self):
        """Sequência da primeira página."""
        return self.xml_adapter.fpage_seq
    
    @cached_property
    def lpage(self):
        """Última página do artigo."""
        return self.xml_adapter.lpage
    
    @cached_property
    def pub_year(self):
        """Ano de publicação."""
        return self.xml_adapter.pub_year
    
    @cached_property
    def volume(self):
        """Volume da publicação."""
        return self.xml_adapter.volume
    
    @cached_property
    def number(self):
        """Número/fascículo da publicação."""
        return self.xml_adapter.number
    
    @cached_property
    def suppl(self):
        """Suplemento da publicação."""
        return self.xml_adapter.suppl
    
    @cached_property
    def z_surnames(self):
        """Sobrenomes dos autores concatenados."""
        return self.xml_adapter.z_surnames
    
    @cached_property
    def z_collab(self):
        """Colaborações do artigo."""
        return self.xml_adapter.z_collab
    
    @cached_property
    def z_links(self):
        """Links relacionados ao artigo."""
        return self.xml_adapter.z_links
    
    @cached_property
    def z_partial_body(self):
        """Conteúdo parcial do corpo do artigo."""
        return self.xml_adapter.z_partial_body

    @cached_property
    def order(self):
        """Conteúdo parcial do corpo do artigo."""
        return self.xml_adapter.order
    
    # ========== Queries Construídas ==========
    
    @property
    def identifier_queries(self):
        """
        Constrói queries para busca por identificadores (v3, v2, aop_pid, pkg_name, DOI).
        """
        q = Q()
        other_pids = set()
        
        # PIDs diretos do xml_adapter (não envelopados no data dict)
        v3 = self.xml_adapter.v3
        v2 = self.xml_adapter.v2
        aop_pid = self.xml_adapter.aop_pid
    
        # PID v3 - máxima prioridade
        if v3:
            q |= Q(v3=v3)
        
        # PID v2
        if v2:
            q |= Q(v2=v2)
        
        # AOP PID
        if aop_pid:
            q |= Q(v2=aop_pid) | Q(aop_pid=aop_pid)
            
        # Package names históricos e atuais
        pkg_names = self.pkg_name_list
        if pkg_names:
            q |= Q(pkg_name__in=pkg_names)

        main_doi = self.adapter_data.get("main_doi")
        if main_doi:
            q |= Q(main_doi=main_doi)
            
        return q
    
    @property
    def issn_query(self):
        """
        Constrói query base para busca por ISSN (eletrônico ou impresso).
        """
        q = Q()
        issn_electronic = self.adapter_data.get("issn_electronic")
        issn_print = self.adapter_data.get("issn_print")
        
        if not issn_electronic and not issn_print:
            raise exceptions.RequiredISSNErrorToGetPidProviderXMLError(
                _("Required Print or Electronic ISSN to identify XML {}").format(
                    self.xml_adapter.pkg_name,
                )
            )
        
        if issn_electronic:
            q |= Q(issn_electronic=issn_electronic)
        
        if issn_print:
            q |= Q(issn_print=issn_print)
        
        return q
           
    @cached_property
    def issue_params(self):
        """
        Constrói dicionário com metadados do fascículo e paginação do artigo.
        
        Retorna todos os campos sem verificar presença, permitindo
        que o ORM do Django filtre automaticamente valores None.
        
        Returns
        -------
        dict
            Dicionário com elocation_id, fpage, fpage_seq, lpage, 
            pub_year, volume, number e suppl
        """
        data = {
            "elocation_id": self.elocation_id,
            "fpage": self.fpage,
            "fpage_seq": self.fpage_seq,
            "lpage": self.lpage,
            "pub_year": self.pub_year,
            "volume": self.volume,
            "number": self.number,
            "suppl": self.suppl,
        }
        if self.order:
            data["v2__endswith"] = self.order
        elif not self.elocation_id and not self.fpage and self.main_doi:
            data["main_doi__iexact"] = self.main_doi
        return data
    
    @cached_property
    def article_data_query(self):
        """
        Constrói query para busca por dados textuais do artigo.
        
        Combina buscas por sobrenomes de autores, colaborações,
        links e conteúdo parcial do corpo do artigo.
        
        Returns
        -------
        Q or None
            Query object combinando z_surnames, z_collab, z_links e z_partial_body,
            ou None se nenhum dado textual estiver disponível
        """
        # Verifica se há algum dado textual disponível
        if not any([
            self.z_surnames,
            self.z_collab,
            self.z_links,
            self.z_partial_body,
        ]):
            return Q(
                z_surnames=self.z_surnames,
                z_collab=self.z_collab,
                z_links=self.z_links,
                z_partial_body=self.z_partial_body,
            )
        
        q = Q()
        
        # Adiciona query para sobrenomes se disponível
        if self.z_surnames:
            q |= Q(z_surnames=self.z_surnames)
        
        # Adiciona queries para outros campos textuais
        if self.z_collab:
            q |= Q(z_collab=self.z_collab)
        
        if self.z_links:
            q |= Q(z_links=self.z_links)
        
        if self.z_partial_body:
            q |= Q(z_partial_body=self.z_partial_body)
        
        return q