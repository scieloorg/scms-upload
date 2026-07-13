from django.test import TestCase
from unittest.mock import MagicMock, patch
from pid_provider.models import PidProviderXML


class PidProviderXMLSelectRecordTests(TestCase):
    """
    Testes de select_record com get_best_match totalmente mockado
    (get_best_match já tem cobertura própria em outro arquivo).
    """

    def _make_query_set(self, exists=True, count=0):
        query_set = MagicMock()
        query_set.exists.return_value = exists
        query_set.count.return_value = count
        return query_set

    def _make_xml_adapter(self, data_to_compare=None):
        xml_adapter = MagicMock()
        xml_adapter.get_data_to_compare.return_value = data_to_compare or {}
        return xml_adapter

    @patch("pid_provider.models.PidProviderXML.get_best_match")
    def test_select_record_returns_empty_dict_when_no_selection_results(self, mock_get_best_match):
        """Sem nenhum label/query_set, retorna dict vazio e nem chama get_best_match."""

        xml_adapter = self._make_xml_adapter()

        result = PidProviderXML.select_record(xml_adapter, [])

        self.assertEqual(result, {})
        mock_get_best_match.assert_not_called()
        xml_adapter.get_data_to_compare.assert_called_once()

    @patch("pid_provider.models.PidProviderXML.get_best_match")
    def test_select_record_skips_falsy_or_nonexistent_query_sets(self, mock_get_best_match):
        """query_set falsy (ex.: lista vazia) ou sem .exists() devem ser pulados, sem chamar get_best_match."""

        empty_query_set = []  # "not query_set" é True -> pulado antes de checar .exists()
        nonexistent_query_set = self._make_query_set(exists=False)

        xml_adapter = self._make_xml_adapter()
        selection_results = [
            ("empty_label", empty_query_set),
            ("nonexistent_label", nonexistent_query_set),
        ]

        result = PidProviderXML.select_record(xml_adapter, selection_results)

        self.assertEqual(result, {})
        mock_get_best_match.assert_not_called()

    @patch("pid_provider.models.PidProviderXML.get_best_match")
    def test_select_record_uses_matched_list_as_is_no_double_slice(self, mock_get_best_match):
        """
        CORRIGIDO: matched_items agora usa a lista "matched" tal como veio de
        get_best_match, sem fatiar de novo -- nenhum item deve se perder.
        """

        query_set = self._make_query_set(exists=True, count=5)
        xml_adapter = self._make_xml_adapter()

        mock_get_best_match.return_value = {
            "registered": "ITEM_1",
            "matched": ["ITEM_2_DATA", "ITEM_3_DATA"],
            # sem "unmatched": todos os candidatos foram aprovados
        }

        result = PidProviderXML.select_record(xml_adapter, [("journal", query_set)])

        self.assertEqual(result["total_results"], 5)
        self.assertEqual(result["registered"], "ITEM_1")
        # Sem re-fatiamento: os 2 itens de "matched" continuam intactos
        self.assertEqual(result["matched_items"], {"journal": ["ITEM_2_DATA", "ITEM_3_DATA"]})
        self.assertNotIn("unmatched_items", result)

    @patch("pid_provider.models.PidProviderXML.get_best_match")
    def test_select_record_single_approved_item_returns_response_without_matched_key(self, mock_get_best_match):
        """
        CORRIGIDO: com apenas 1 candidato aprovado, get_best_match não retorna "matched",
        só "registered". Antes isso caía (erroneamente) no branch de unmatched_items;
        agora o gatilho é "if registered:", então a resposta correta é retornada mesmo
        sem a chave "matched_items".
        """

        query_set = self._make_query_set(exists=True, count=1)
        xml_adapter = self._make_xml_adapter()

        mock_get_best_match.return_value = {
            "registered": "ITEM_1",
            # sem "matched": só havia 1 candidato aprovado
        }

        result = PidProviderXML.select_record(xml_adapter, [("journal", query_set)])

        self.assertEqual(result["total_results"], 1)
        self.assertEqual(result["registered"], "ITEM_1")
        self.assertNotIn("matched_items", result)
        self.assertNotIn("unmatched_items", result)

    @patch("pid_provider.models.PidProviderXML.get_best_match")
    def test_select_record_includes_unmatched_items_alongside_matched(self, mock_get_best_match):
        """Quando há "registered"/"matched" E "unmatched" no mesmo label, ambos aparecem na resposta."""

        query_set = self._make_query_set(exists=True, count=4)
        xml_adapter = self._make_xml_adapter()

        mock_get_best_match.return_value = {
            "registered": "ITEM_1",
            "matched": ["ITEM_2_DATA", "ITEM_3_DATA"],
            "unmatched": ["ITEM_4_DATA"],
        }

        result = PidProviderXML.select_record(xml_adapter, [("journal", query_set)])

        self.assertEqual(result["matched_items"], {"journal": ["ITEM_2_DATA", "ITEM_3_DATA"]})
        self.assertEqual(result["unmatched_items"], {"journal": ["ITEM_4_DATA"]})

    @patch("pid_provider.models.PidProviderXML.get_best_match")
    def test_select_record_no_registered_stores_actual_unmatched_list(self, mock_get_best_match):
        """
        CORRIGIDO: quando get_best_match não retorna "registered" (nenhum candidato
        aprovado) mas retorna "unmatched", unmatched_items[label] agora recebe a lista
        real ["ITEM_X_DATA"], e não mais uma auto-referência ao dicionário acumulador.
        """

        query_set = self._make_query_set(exists=True, count=1)
        xml_adapter = self._make_xml_adapter()

        mock_get_best_match.return_value = {
            "unmatched": ["ITEM_X_DATA"],
            # sem "registered": nenhum candidato passou do corte
        }

        result = PidProviderXML.select_record(xml_adapter, [("journal", query_set)])

        self.assertEqual(result, {"unmatched_items": {"journal": ["ITEM_X_DATA"]}})

    @patch("pid_provider.models.PidProviderXML.get_best_match")
    def test_select_record_returns_on_first_label_with_registered_ignoring_earlier_unmatched(self, mock_get_best_match):
        """
        Ao encontrar o primeiro label com "registered", a função retorna imediatamente --
        o que foi acumulado em unmatched_items para labels anteriores é descartado.
        """

        query_set_1 = self._make_query_set(exists=True, count=1)
        query_set_2 = self._make_query_set(exists=True, count=3)
        xml_adapter = self._make_xml_adapter()

        mock_get_best_match.side_effect = [
            {"unmatched": ["LABEL1_UNMATCHED_DATA"]},  # label1: sem "registered"
            {
                "registered": "LABEL2_ITEM_1",
                "matched": ["LABEL2_ITEM_2_DATA", "LABEL2_ITEM_3_DATA"],
            },  # label2: com "registered"
        ]

        selection_results = [
            ("label1", query_set_1),
            ("label2", query_set_2),
        ]

        result = PidProviderXML.select_record(xml_adapter, selection_results)

        self.assertEqual(result["total_results"], 3)
        self.assertEqual(result["registered"], "LABEL2_ITEM_1")
        self.assertEqual(result["matched_items"], {"label2": ["LABEL2_ITEM_2_DATA", "LABEL2_ITEM_3_DATA"]})
        self.assertNotIn("unmatched_items", result)
        self.assertNotIn("label1", result)

    @patch("pid_provider.models.PidProviderXML.get_best_match")
    def test_select_record_accumulates_actual_unmatched_lists_across_labels_when_none_registered(self, mock_get_best_match):
        """
        CORRIGIDO: quando nenhum label produz "registered", a função percorre todos e
        retorna {"unmatched_items": unmatched_items} ao final, com cada label apontando
        para sua própria lista de não aprovados (não mais para o dict acumulador).
        """

        query_set_1 = self._make_query_set(exists=True, count=1)
        query_set_2 = self._make_query_set(exists=True, count=1)
        xml_adapter = self._make_xml_adapter()

        mock_get_best_match.side_effect = [
            {"unmatched": ["L1_DATA"]},
            {"unmatched": ["L2_DATA"]},
        ]

        selection_results = [
            ("label1", query_set_1),
            ("label2", query_set_2),
        ]

        result = PidProviderXML.select_record(xml_adapter, selection_results)

        self.assertEqual(
            result,
            {"unmatched_items": {"label1": ["L1_DATA"], "label2": ["L2_DATA"]}},
        )

    @patch("pid_provider.models.PidProviderXML.get_best_match")
    def test_select_record_passes_query_set_and_comparison_data_to_get_best_match(self, mock_get_best_match):
        """get_best_match deve ser chamado com o query_set do label e os dados já processados do xml_adapter."""

        query_set = self._make_query_set(exists=True, count=1)
        xml_adapter = self._make_xml_adapter(data_to_compare={"title": "Foo"})

        mock_get_best_match.return_value = {"unmatched": ["ITEM_DATA"]}

        PidProviderXML.select_record(xml_adapter, [("journal", query_set)])

        mock_get_best_match.assert_called_once_with(query_set, {"title": "Foo"})