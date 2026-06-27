from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import TestCase

from pid_provider.models import PidProviderXML
from pid_provider.exceptions import UnmatchedPidProviderXMLError


User = get_user_model()


class PidProviderXMLGetRecordsTests(TestCase):

    def setUp(self):
        # Cria um usuário para satisfazer a restrição de 'creator_id'
        self.user = User.objects.create_user(username="testuser", password="password")
        
        # Mocks existentes...
        self.xml_adapter_mock = MagicMock()
        self.xml_adapter_mock.xml_with_pre.article_titles_texts = "Titulo de Teste"
        self.xml_adapter_mock.z_surnames = "Silva"
        self.xml_adapter_mock.z_collab = None
        self.xml_adapter_mock.z_links = None
        self.xml_adapter_mock.z_partial_body = "Corpo parcial do artigo"
        self.xml_adapter_mock.sps_pkg_name = "test_package"

    @patch("pid_provider.models.QueryBuilderPidProviderXML")
    @patch.object(PidProviderXML, "best_matches")
    def test_get_records_by_identifiers_success(self, mock_best_matches, mock_qbuilder_cls):
        """1) Deve retornar o registro quando encontrado por identificadores diretos."""
        # Configura o mock do QueryBuilder
        mock_qbuilder = mock_qbuilder_cls.return_value
        mock_qbuilder.identifier_queries = Q(v3="12345")
        
        # Cria um registro no banco que case com a query
        record = PidProviderXML.objects.create(creator=self.user, v3="12345", registered_in_core=True)
        
        # Mock do retorno do best_matches
        expected_result = {"registered": record, "total_results": 1}
        mock_best_matches.return_value = expected_result

        # Executa o método
        result = PidProviderXML.get_records(self.xml_adapter_mock)

        # Validações
        self.assertEqual(result, expected_result)
        mock_best_matches.assert_called_once_with([record], self.xml_adapter_mock)

    @patch("pid_provider.models.QueryBuilderPidProviderXML")
    @patch.object(PidProviderXML, "best_matches")
    def test_get_records_by_journal_and_issue_and_article_success(self, mock_best_matches, mock_qbuilder_cls):
        """2) Deve encontrar o registro por Journal + Issue + Dados do Artigo quando os IDs falharem."""
        mock_qbuilder = mock_qbuilder_cls.return_value
        # Força falha no passo 1
        mock_qbuilder.identifier_queries = Q(v3="id_inexistente")
        
        # Configura os passos do fluxo de fallback
        mock_qbuilder.issn_query = Q(issn_print="1234-5678")
        mock_qbuilder.issue_params = {"pub_year": 2026}
        mock_qbuilder.article_data_query = Q(z_surnames="Silva")

        # Cria o registro correspondente no banco
        record = PidProviderXML.objects.create(creator=self.user, 
            issn_print="1234-5678", 
            z_surnames="Silva",
            v3="outro_id"
        )
        
        expected_result = {"registered": record, "total_results": 1}
        mock_best_matches.return_value = expected_result

        result = PidProviderXML.get_records(self.xml_adapter_mock)

        self.assertEqual(result, expected_result)
        mock_best_matches.assert_called_once_with([record], self.xml_adapter_mock)

    @patch("pid_provider.models.QueryBuilderPidProviderXML")
    @patch.object(PidProviderXML, "best_matches")
    def test_get_records_by_journal_and_article_only_success(self, mock_best_matches, mock_qbuilder_cls):
        """3) Deve encontrar o registro por Journal + Dados do Artigo (ignorando Issue) se os passos anteriores falharem."""
        mock_qbuilder = mock_qbuilder_cls.return_value
        # Força falha nos passos 1 e 2
        mock_qbuilder.identifier_queries = Q(v3="id_inexistente")
        mock_qbuilder.issn_query = Q(issn_print="1234-5678")
        mock_qbuilder.issue_params = {"pub_year": 9999}  # Ano errado para falhar o passo 2
        mock_qbuilder.article_data_query = Q(z_surnames="Silva")

        # Registro no banco compartilha apenas o ISSN e o dado do artigo (o ano/issue seria diferente)
        record = PidProviderXML.objects.create(creator=self.user, 
            issn_print="1234-5678", 
            z_surnames="Silva"
        )
        
        expected_result = {"registered": record, "total_results": 1}
        mock_best_matches.return_value = expected_result

        result = PidProviderXML.get_records(self.xml_adapter_mock)

        self.assertEqual(result, expected_result)
        mock_best_matches.assert_called_once_with([record], self.xml_adapter_mock)

    @patch("pid_provider.models.QueryBuilderPidProviderXML")
    @patch.object(PidProviderXML, "best_matches")
    def test_get_records_raises_does_not_exist(self, mock_best_matches, mock_qbuilder_cls):
        """4) Deve levantar PidProviderXML.DoesNotExist se nenhuma das estratégias encontrar candidatos."""
        mock_qbuilder = mock_qbuilder_cls.return_value
        mock_qbuilder.identifier_queries = Q(v3="nao_existe")
        mock_qbuilder.issn_query = Q(issn_print="0000-0000")
        mock_qbuilder.issue_params = {}
        mock_qbuilder.article_data_query = Q(z_surnames="Ninguém")

        with self.assertRaises(PidProviderXML.DoesNotExist):
            PidProviderXML.get_records(self.xml_adapter_mock)
            
        # O best_matches nunca deve ter sido chamado porque nenhuma lista de candidatos foi gerada
        mock_best_matches.assert_not_called()

    @patch("pid_provider.models.QueryBuilderPidProviderXML")
    @patch.object(PidProviderXML, "best_matches")
    def test_get_records_fallback_when_best_matches_returns_no_registered(self, mock_best_matches, mock_qbuilder_cls):
        """5) Se o passo 1 achar candidatos mas o best_matches não validar um 'registered', deve prosseguir para o passo seguinte."""
        mock_qbuilder = mock_qbuilder_cls.return_value
        mock_qbuilder.identifier_queries = Q(v3="id_com_score_baixo")
        mock_qbuilder.issn_query = Q(issn_print="1234-5678")
        mock_qbuilder.issue_params = {"pub_year": 2026}
        mock_qbuilder.article_data_query = Q(z_surnames="Silva")

        # Cria candidato para o passo 1 e o alvo real para o passo 2
        candidato_ruim = PidProviderXML.objects.create(creator=self.user, v3="id_com_score_baixo")
        alvo_correto = PidProviderXML.objects.create(creator=self.user, issn_print="1234-5678", z_surnames="Silva")

        # Configura o mock do best_matches para simular comportamento diferente por chamada
        # 1ª chamada (Passo 1): Encontra resultado mas sem a chave 'registered' validada (percentual baixo)
        # 2ª chamada (Passo 2): Encontra e valida o 'registered'
        mock_best_matches.side_effect = [
            {"registered": None, "failed": [candidato_ruim]},
            {"registered": alvo_correto, "total_results": 1}
        ]

        result = PidProviderXML.get_records(self.xml_adapter_mock)

        self.assertEqual(result["registered"], alvo_correto)
        self.assertEqual(mock_best_matches.call_count, 2)