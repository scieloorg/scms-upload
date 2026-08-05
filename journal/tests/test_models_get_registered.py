"""
journal/tests/test_models_get_registered.py

Testes para Journal.get_registered (journal/models.py).

AJUSTE NECESSÁRIO:
O import abaixo assume `journal.models.Journal`. Ajuste se necessário.

Baseado em unittest (unittest.TestCase + unittest.mock).

Estratégia: `Journal.objects` é substituído por um MagicMock via
patch.object, para controlar precisamente as sequências de retorno ou
exceção de `.get()` e `.filter(...).order_by(...).first()`, sem
depender de banco de dados real. As exceções usadas
(Journal.DoesNotExist, Journal.MultipleObjectsReturned) são as classes
reais geradas automaticamente pelo Django para o model Journal — não
são mocks, então o comportamento de try/except do código sob teste é
exercitado de verdade.
"""

import unittest
from unittest.mock import MagicMock, patch

from django.db.models import Q

from journal.models import Journal  # <-- ajuste este import se necessário


def configure_filter_chain(mock_manager, result):
    """
    Configura mock_manager.filter(...).order_by(...).first() para
    retornar `result`.
    """
    mock_manager.filter.return_value.order_by.return_value.first.return_value = result


# ---------------------------------------------------------------------------
# Match exato (issn_electronic / issn_print na ordem correta)
# ---------------------------------------------------------------------------

class TestGetRegisteredMatchExato(unittest.TestCase):

    def setUp(self):
        patcher = patch.object(Journal, "objects", new_callable=MagicMock)
        self.mock_manager = patcher.start()
        self.addCleanup(patcher.stop)

    def test_retorna_journal_quando_ha_match_exato(self):
        journal_obj = MagicMock(name="journal_exato")
        self.mock_manager.get.return_value = journal_obj

        result = Journal.get_registered("Revista X", "1678-4464", "0102-311X")

        self.assertIs(result, journal_obj)
        self.mock_manager.get.assert_called_once_with(
            official_journal__issn_electronic="1678-4464",
            official_journal__issn_print="0102-311X",
        )
        self.mock_manager.filter.assert_not_called()

    def test_match_exato_ambiguo_usa_filter_com_valores_originais(self):
        journal_obj = MagicMock(name="journal_desambiguado")
        self.mock_manager.get.side_effect = Journal.MultipleObjectsReturned()
        configure_filter_chain(self.mock_manager, journal_obj)

        result = Journal.get_registered("Revista X", "1678-4464", "0102-311X")

        self.assertIs(result, journal_obj)
        self.mock_manager.filter.assert_called_once_with(
            official_journal__issn_electronic="1678-4464",
            official_journal__issn_print="0102-311X",
        )
        self.mock_manager.filter.return_value.order_by.assert_called_once_with(
            "-updated"
        )


# ---------------------------------------------------------------------------
# Match trocado (issn_electronic / issn_print invertidos)
# ---------------------------------------------------------------------------

class TestGetRegisteredMatchTrocado(unittest.TestCase):

    def setUp(self):
        patcher = patch.object(Journal, "objects", new_callable=MagicMock)
        self.mock_manager = patcher.start()
        self.addCleanup(patcher.stop)

    def test_retorna_journal_quando_ha_match_trocado_exato(self):
        journal_obj = MagicMock(name="journal_trocado")
        self.mock_manager.get.side_effect = [
            Journal.DoesNotExist(),
            journal_obj,
        ]

        result = Journal.get_registered("Revista X", "1678-4464", "0102-311X")

        self.assertIs(result, journal_obj)
        self.assertEqual(self.mock_manager.get.call_count, 2)
        segunda_chamada = self.mock_manager.get.call_args_list[1]
        self.assertEqual(
            segunda_chamada.kwargs,
            {
                "official_journal__issn_electronic": "0102-311X",
                "official_journal__issn_print": "1678-4464",
            },
        )

    def test_match_trocado_ambiguo_usa_filter_com_valores_trocados(self):
        journal_obj = MagicMock(name="journal_trocado_desambiguado")
        self.mock_manager.get.side_effect = [
            Journal.DoesNotExist(),
            Journal.MultipleObjectsReturned(),
        ]
        configure_filter_chain(self.mock_manager, journal_obj)

        result = Journal.get_registered("Revista X", "1678-4464", "0102-311X")

        self.assertIs(result, journal_obj)
        self.mock_manager.filter.assert_called_once_with(
            official_journal__issn_electronic="0102-311X",
            official_journal__issn_print="1678-4464",
        )
        self.mock_manager.filter.return_value.order_by.assert_called_once_with(
            "-updated"
        )


# ---------------------------------------------------------------------------
# Fallback final por Q (OR) sobre o conjunto de ISSNs
# ---------------------------------------------------------------------------

class TestGetRegisteredFallbackFinal(unittest.TestCase):
    """
    Cobre o caso em que nem o match exato nem o trocado existem, caindo
    no fallback final por Q (OR) sobre o conjunto de ISSNs informados.
    """

    def setUp(self):
        patcher = patch.object(Journal, "objects", new_callable=MagicMock)
        self.mock_manager = patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _expected_q(issn_electronic, issn_print):
        issns = set()
        if issn_electronic:
            issns.add(issn_electronic)
        if issn_print:
            issns.add(issn_print)
        return (
            Q(official_journal__issn_electronic__in=issns)
            | Q(official_journal__issn_print__in=issns)
        )

    def test_fallback_final_retorna_journal_quando_encontrado(self):
        journal_obj = MagicMock(name="journal_fallback")
        self.mock_manager.get.side_effect = [
            Journal.DoesNotExist(),
            Journal.DoesNotExist(),
        ]
        configure_filter_chain(self.mock_manager, journal_obj)

        result = Journal.get_registered("Revista X", "1678-4464", "0102-311X")

        self.assertIs(result, journal_obj)
        self.mock_manager.filter.assert_called_once_with(
            self._expected_q("1678-4464", "0102-311X")
        )
        self.mock_manager.filter.return_value.order_by.assert_called_once_with(
            "-updated"
        )

    def test_fallback_final_levanta_does_not_exist_quando_nao_encontra(self):
        self.mock_manager.get.side_effect = [
            Journal.DoesNotExist(),
            Journal.DoesNotExist(),
        ]
        configure_filter_chain(self.mock_manager, None)

        with self.assertRaises(Journal.DoesNotExist):
            Journal.get_registered("Revista X", "1678-4464", "0102-311X")

    def test_fallback_final_com_apenas_issn_eletronico(self):
        """
        Quando issn_print é None/vazio, `issns` contém apenas
        issn_electronic — o fallback final ainda assim funciona
        corretamente (diferente do ramo "trocado", ver classe abaixo).
        """
        journal_obj = MagicMock(name="journal_fallback_issn_unico")
        self.mock_manager.get.side_effect = [
            Journal.DoesNotExist(),
            Journal.DoesNotExist(),
        ]
        configure_filter_chain(self.mock_manager, journal_obj)

        result = Journal.get_registered("Revista X", "1678-4464", None)

        self.assertIs(result, journal_obj)
        self.mock_manager.filter.assert_called_once_with(
            self._expected_q("1678-4464", None)
        )


# ---------------------------------------------------------------------------
# Comportamento conhecido quando falta ISSN no ramo "trocado"
# ---------------------------------------------------------------------------

class TestGetRegisteredIssnAusenteNoRamoTrocado(unittest.TestCase):
    """
    Documenta o comportamento ATUAL (conhecido, mantido por decisão do
    time) quando issn_print está ausente: a segunda chamada a `.get()`
    (ramo "trocado") passa a comparar
    `official_journal__issn_electronic=None`, o que deixa de significar
    "verificar troca de ISSN" e pode, em tese, casar com qualquer
    Journal sem ISSN eletrônico cadastrado cujo issn_print seja igual a
    issn_electronic. Este teste não valida que esse comportamento é o
    "certo" — apenas fixa o que a função faz hoje, para que qualquer
    mudança futura nesse ponto seja deliberada e não acidental.
    """

    def setUp(self):
        patcher = patch.object(Journal, "objects", new_callable=MagicMock)
        self.mock_manager = patcher.start()
        self.addCleanup(patcher.stop)

    def test_segunda_chamada_get_usa_issn_electronic_none_como_criterio(self):
        journal_obj = MagicMock(name="journal_sem_issn_eletronico")
        self.mock_manager.get.side_effect = [
            Journal.DoesNotExist(),
            journal_obj,
        ]

        result = Journal.get_registered("Revista X", "1678-4464", None)

        self.assertIs(result, journal_obj)
        segunda_chamada = self.mock_manager.get.call_args_list[1]
        self.assertEqual(
            segunda_chamada.kwargs,
            {
                "official_journal__issn_electronic": None,
                "official_journal__issn_print": "1678-4464",
            },
        )


if __name__ == "__main__":
    unittest.main()