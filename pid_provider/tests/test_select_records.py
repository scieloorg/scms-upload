from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import TestCase

from pid_provider.models import PidProviderXML


User = get_user_model()


def build_get_article_data_query_side_effect(queries):
    """
    Constrói o side_effect para `qbuilder.get_article_data_query(issue, flexible)`.

    `queries` é um dict {(issue, flexible): Q(...)} com as 4 combinações
    possíveis dos dois eixos independentes que o método agora recebe.
    """
    def _side_effect(issue, flexible):
        return queries[(issue, flexible)]
    return _side_effect


class PidProviderXMLSelectRecordsTests(TestCase):
    """
    select_records é um generator: apenas yield-a tuplas
    (label, lista_de_candidatos_materializada) com os candidatos de
    cada estratégia de busca. Cada branch é convertida com list(...)
    dentro do próprio método (ver docstring de select_records), então
    o que chega aqui NÃO é mais um QuerySet — é uma list — e portanto
    não expõe métodos como .count() ou .filter().
    Ele NÃO chama mais best_matches nem levanta DoesNotExist —
    essa orquestração ficou fora deste método.

    MUDANÇA DE CONTRATO: agora são 3 branches -- "ids",
    "journal-issue-article-strict" e "journal-issue-article-flexible" --
    e as duas últimas combinam via OR as variantes com/sem issue de
    `qbuilder.get_article_data_query(issue, flexible)`, que ganhou o
    segundo eixo `flexible` (False = exige article_data_query, como
    antes; True = dispensa, casando só por fascículo/localização).
    Também, "ids" só filtra quando `identifier_queries != Q()` -- uma Q
    vazia produz lista vazia sem tocar o banco.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")

        self.xml_adapter_mock = MagicMock()
        self.xml_adapter_mock.xml_with_pre.article_titles_texts = "Titulo de Teste"
        self.xml_adapter_mock.z_surnames = "Silva"
        self.xml_adapter_mock.z_collab = None
        self.xml_adapter_mock.z_links = None
        self.xml_adapter_mock.z_partial_body = "Corpo parcial do artigo"
        self.xml_adapter_mock.sps_pkg_name = "test_package"

    @patch("pid_provider.models.QueryBuilderPidProviderXML")
    def test_select_records_yields_three_labeled_lists_in_order(self, mock_qbuilder_cls):
        """O generator deve produzir, nesta ordem: ids, journal-issue-article-strict, journal-issue-article-flexible."""
        mock_qbuilder = mock_qbuilder_cls.return_value
        mock_qbuilder.identifier_queries = Q(v3="12345")
        mock_qbuilder.issn_query = Q(issn_print="1234-5678")

        # strict (flexible=False): só o registro com pub_year=2026 bate
        # (issue=False,flexible=False vira um filtro que não bate em nada aqui)
        # flexible (flexible=True): qualquer registro com z_surnames="Silva" bate,
        # incluindo o que só tem pub_year=1999
        mock_qbuilder.get_article_data_query.side_effect = (
            build_get_article_data_query_side_effect({
                (True, False): Q(pub_year=2026, z_surnames="Silva"),
                (False, False): Q(pub_year=9999),
                (True, True): Q(pub_year=2026),
                (False, True): Q(z_surnames="Silva"),
            })
        )

        record_by_id = PidProviderXML.objects.create(
            creator=self.user, v3="12345", registered_in_core=True
        )
        record_strict = PidProviderXML.objects.create(
            creator=self.user,
            issn_print="1234-5678",
            pub_year=2026,
            z_surnames="Silva",
        )
        record_flexible_only = PidProviderXML.objects.create(
            creator=self.user,
            issn_print="1234-5678",
            pub_year=1999,
            z_surnames="Silva",
        )

        results = list(PidProviderXML.select_records(self.xml_adapter_mock))

        mock_qbuilder.validate_input_data.assert_called_once()

        self.assertEqual(len(results), 3)

        labels = [label for label, _ in results]
        self.assertEqual(
            labels,
            ["ids", "journal-issue-article-strict", "journal-issue-article-flexible"],
        )

        # cada branch já vem materializada como list (não QuerySet)
        for _label, candidates in results:
            self.assertIsInstance(candidates, list)

        # get_article_data_query deve ter sido chamado com as 4 combinações
        # (issue, flexible), nesta ordem: (True, False), (False, False),
        # (True, True), (False, True)
        calls = [
            (c.kwargs.get("issue"), c.kwargs.get("flexible"))
            for c in mock_qbuilder.get_article_data_query.call_args_list
        ]
        self.assertEqual(
            calls, [(True, False), (False, False), (True, True), (False, True)]
        )

        # 1) ids: só o registro com v3 correspondente
        ids_list = results[0][1]
        self.assertIn(record_by_id, ids_list)
        self.assertNotIn(record_strict, ids_list)
        self.assertNotIn(record_flexible_only, ids_list)

        # 2) journal-issue-article-strict: só o que bate no pub_year certo
        strict_list = results[1][1]
        self.assertIn(record_strict, strict_list)
        self.assertNotIn(record_flexible_only, strict_list)

        # 3) journal-issue-article-flexible: pega os dois (dispensa pub_year)
        flexible_list = results[2][1]
        self.assertIn(record_strict, flexible_list)
        self.assertIn(record_flexible_only, flexible_list)

    @patch("pid_provider.models.QueryBuilderPidProviderXML")
    def test_select_records_empty_lists_when_no_match(self, mock_qbuilder_cls):
        """Sem nenhum registro correspondente, cada lista yield deve vir vazia (sem levantar exceção)."""
        mock_qbuilder = mock_qbuilder_cls.return_value
        mock_qbuilder.identifier_queries = Q(v3="nao_existe")
        mock_qbuilder.issn_query = Q(issn_print="0000-0000")
        mock_qbuilder.get_article_data_query.side_effect = (
            build_get_article_data_query_side_effect({
                (True, False): Q(pub_year=1900, z_surnames="Ninguem"),
                (False, False): Q(pub_year=1900, z_surnames="Ninguem"),
                (True, True): Q(z_surnames="Ninguem"),
                (False, True): Q(z_surnames="Ninguem"),
            })
        )

        results = list(PidProviderXML.select_records(self.xml_adapter_mock))

        self.assertEqual(len(results), 3)
        for _label, candidates in results:
            self.assertIsInstance(candidates, list)
            # listas usam len(), não .count() (que é método de QuerySet)
            self.assertEqual(len(candidates), 0)

    @patch("pid_provider.models.QueryBuilderPidProviderXML")
    def test_select_records_ids_is_empty_without_query_when_identifier_queries_is_empty(
        self, mock_qbuilder_cls
    ):
        """
        Quando identifier_queries é Q() (nenhum identificador no XML de
        entrada), a branch "ids" produz [] diretamente, SEM filtrar o
        banco -- filter(Q()) traria todos os registros, o que não é o
        comportamento desejado para "nenhum critério".
        """
        mock_qbuilder = mock_qbuilder_cls.return_value
        mock_qbuilder.identifier_queries = Q()
        mock_qbuilder.issn_query = Q(issn_print="0000-0000")
        mock_qbuilder.get_article_data_query.side_effect = (
            build_get_article_data_query_side_effect({
                (True, False): Q(pub_year=1900),
                (False, False): Q(pub_year=1900),
                (True, True): Q(pub_year=1900),
                (False, True): Q(pub_year=1900),
            })
        )

        PidProviderXML.objects.create(
            creator=self.user, v3="ANY", issn_print="0000-0000"
        )

        results = dict(PidProviderXML.select_records(self.xml_adapter_mock))

        self.assertEqual(results["ids"], [])

    @patch("pid_provider.models.QueryBuilderPidProviderXML")
    def test_select_records_is_lazy_until_iterated(self, mock_qbuilder_cls):
        """
        Por ser generator, nada é executado na chamada da função:
        QueryBuilderPidProviderXML(...) e validate_input_data() só
        rodam quando o generator é de fato consumido (primeiro next()).
        get_article_data_query só é chamado a partir do 2º/3º next(),
        já que a 1ª branch ("ids") não depende dele -- e cada uma dessas
        branches chama get_article_data_query DUAS vezes (issue=True e
        issue=False), pois o OR precisa avaliar os dois lados.
        """
        mock_qbuilder = mock_qbuilder_cls.return_value
        mock_qbuilder.identifier_queries = Q(v3="qualquer")
        mock_qbuilder.issn_query = Q(issn_print="0000-0000")
        mock_qbuilder.get_article_data_query.side_effect = (
            build_get_article_data_query_side_effect({
                (True, False): Q(),
                (False, False): Q(),
                (True, True): Q(),
                (False, True): Q(),
            })
        )

        gen = PidProviderXML.select_records(self.xml_adapter_mock)

        # nada foi executado ainda
        mock_qbuilder_cls.assert_not_called()
        mock_qbuilder.validate_input_data.assert_not_called()

        next(gen)  # yield "ids"

        mock_qbuilder_cls.assert_called_once_with(self.xml_adapter_mock)
        mock_qbuilder.validate_input_data.assert_called_once()
        # "ids" não usa get_article_data_query
        mock_qbuilder.get_article_data_query.assert_not_called()

        next(gen)  # yield "journal-issue-article-strict"
        self.assertEqual(mock_qbuilder.get_article_data_query.call_count, 2)
        mock_qbuilder.get_article_data_query.assert_any_call(issue=True, flexible=False)
        mock_qbuilder.get_article_data_query.assert_any_call(issue=False, flexible=False)

        next(gen)  # yield "journal-issue-article-flexible"
        self.assertEqual(mock_qbuilder.get_article_data_query.call_count, 4)
        mock_qbuilder.get_article_data_query.assert_any_call(issue=True, flexible=True)
        mock_qbuilder.get_article_data_query.assert_any_call(issue=False, flexible=True)
