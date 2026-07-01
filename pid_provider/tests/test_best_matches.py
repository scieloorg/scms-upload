from django.test import TestCase
from unittest.mock import MagicMock, patch
from pid_provider.models import PidProviderXML


class PidProviderXMLBestMatchesTests(TestCase):

    def setUp(self):
        # Mock do xml_adapter e das propriedades exigidas por best_matches
        self.xml_adapter_mock = MagicMock()
        self.xml_adapter_mock.xml_with_pre.article_titles_texts = "Titulo Original"
        self.xml_adapter_mock.z_surnames = "Silva; Santos"
        self.xml_adapter_mock.z_collab = "Grupo SpS"
        self.xml_adapter_mock.z_links = "http://link1.com"
        self.xml_adapter_mock.z_partial_body = "Texto do corpo do artigo..."

    @patch("pid_provider.models.compare")
    def test_best_matches_success_with_valid_and_invalid_scores(self, mock_compare):
        """Deve ordenar os resultados por score descrescente e separar entre 'ok' (>0.5) e 'failed' (<=0.5)."""
        
        # Cria mocks para simular instâncias de PidProviderXML do banco de dados
        item_bom = MagicMock(spec=PidProviderXML)
        item_bom.id = 101
        item_bom.updated.isoformat.return_value = "2026-06-27T12:00:00"
        item_bom.data_to_compare = {"title": "Titulo Original", "z_surnames": "Silva; Santos"}

        item_ruim = MagicMock(spec=PidProviderXML)
        item_ruim.id = 102
        item_ruim.updated.isoformat.return_value = "2026-06-27T13:00:00"
        item_ruim.data_to_compare = {"title": "Outro Titulo Completamente Diferente", "z_surnames": "Alves"}

        # Configura o efeito colateral do mock 'compare' baseado no item recebido
        def side_effect_compare(item_data, input_data):
            if item_data["title"] == "Titulo Original":
                return {"id": 101, "percentual_score": 0.95, "match": True}
            return {"id": 102, "percentual_score": 0.20, "match": False}
        
        mock_compare.side_effect = side_effect_compare

        # Executa o método passando a lista materializada de candidatos
        candidates = [item_ruim, item_bom]  # Enviados fora de ordem propositalmente
        result = PidProviderXML.best_matches(candidates, self.xml_adapter_mock)

        # Validações de estrutura e contagem
        self.assertEqual(result["total_results"], 2)
        self.assertEqual(len(result["ok"]), 1)
        self.assertEqual(len(result["failed"]), 1)

        # Valida a ordenação e separação (o de score 0.95 deve ser o 'registered')
        self.assertEqual(result["registered"], item_bom)
        self.assertEqual(result["ok"][0]["id"], 101)
        self.assertEqual(result["failed"][0]["id"], 102)

    @patch("pid_provider.models.compare")
    def test_best_matches_no_candidates_approved(self, mock_compare):
        """Quando nenhum candidato atinge score > 0.5, a chave 'registered' não deve existir no retorno."""
        
        item_fraco = MagicMock(spec=PidProviderXML)
        item_fraco.id = 201
        item_fraco.updated.isoformat.return_value = "2026-06-27T14:00:00"
        item_fraco.data_to_compare = {"title": "Quase igual, mas nao o suficiente"}

        # Mock retorna score abaixo da linha de corte (0.5)
        mock_compare.return_value = {"id": 201, "percentual_score": 0.48, "match": False}

        result = PidProviderXML.best_matches([item_fraco], self.xml_adapter_mock)

        # Validações
        self.assertEqual(result["total_results"], 1)
        self.assertEqual(len(result["ok"]), 0)
        self.assertEqual(len(result["failed"]), 1)
        self.assertNotIn("registered", result)  # Não pode haver match oficial

    @patch("pid_provider.models.compare")
    def test_best_matches_tie_breaking_by_updated_date(self, mock_compare):
        """Em caso de empate no percentual_score, o critério de desempate do sorted() deve usar a data 'updated' descrescente."""
        
        # Dois itens com o mesmo score, mas datas de atualização diferentes
        item_antigo = MagicMock(spec=PidProviderXML)
        item_antigo.id = 301
        item_antigo.updated.isoformat.return_value = "2026-01-01T00:00:00"
        item_antigo.data_to_compare = {"title": "Clone"}

        item_recente = MagicMock(spec=PidProviderXML)
        item_recente.id = 302
        item_recente.updated.isoformat.return_value = "2026-06-27T00:00:00"  # Mais recente
        item_recente.data_to_compare = {"title": "Clone"}

        # Mock retorna o mesmo score alto para ambos
        def side_effect_compare(item_data, input_data):
            items = [
                {"label": "title", "score": 0.9},
                {"label": "title", "score": 0.9},
            ]
            return {"items": items, "percentual_score": 0.90, "total_score": 0.90}
            
        mock_compare.side_effect = side_effect_compare

        # Executa passando o antigo primeiro
        result = PidProviderXML.best_matches([item_antigo, item_recente], self.xml_adapter_mock)

        # Como a ordenação usa reverse=True no par (score, data.isoformat(), id),
        # o item_recente ("2026-06-27...") deve ficar em primeiro lugar na ordenação.
        self.assertEqual(result["registered"], item_recente)