"""
Testes para QueryBuilderPidProviderXML e as funções de comparação
(compare, compare_lists, compare_items, get_score, zero_to_none).

ATENÇÃO: ajuste o caminho de import abaixo (`pid_provider.query_params`)
para o módulo real onde essas classes/funções estão definidas no projeto,
caso seja diferente.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.db.models import Q

from pid_provider import exceptions
from pid_provider.query_params import (
    QueryBuilderPidProviderXML,
    compare,
    compare_items,
    compare_lists,
    get_score,
    zero_to_none,
)


def make_xml_adapter(
    data=None,
    v3=None,
    v2=None,
    aop_pid=None,
    pkg_name=None,
    sps_pkg_name=None,
    deprecated_sps_pkg_name_list=None,
    order=None,
    article_titles=None,
    surnames=None,
    collab=None,
    links=None,
    partial_body=None,
):
    """Monta um mock de xml_adapter com a forma esperada por QueryBuilderPidProviderXML."""
    adapter = MagicMock()
    adapter.data = data or {}
    adapter.get_data_to_compare.return_value = {}
    adapter.v3 = v3
    adapter.v2 = v2
    adapter.aop_pid = aop_pid
    adapter.pkg_name = pkg_name
    adapter.sps_pkg_name = sps_pkg_name
    adapter.order = order
    adapter.xml_with_pre.deprecated_sps_pkg_name_list = deprecated_sps_pkg_name_list or []
    adapter.xml_with_pre.get_article_data.return_value = {
        "article_titles": article_titles or [],
        "surnames": surnames,
        "collab": collab,
        "links": links,
        "partial_body": partial_body,
    }
    return adapter


class ValidateInputDataTests(SimpleTestCase):

    def test_raises_when_pub_year_missing(self):
        adapter = make_xml_adapter(data={})
        qbuilder = QueryBuilderPidProviderXML(adapter)
        with self.assertRaises(
            exceptions.RequiredPublicationYearErrorToGetPidProviderXMLError
        ):
            qbuilder.validate_input_data()

    def test_raises_when_issn_missing(self):
        adapter = make_xml_adapter(data={"pub_year": "2026"})
        qbuilder = QueryBuilderPidProviderXML(adapter)
        with self.assertRaises(exceptions.RequiredISSNErrorToGetPidProviderXMLError):
            qbuilder.validate_input_data()

    def test_passes_when_location_params_present(self):
        """Se houver dado de localização do artigo, retorna sem checar dados textuais."""
        adapter = make_xml_adapter(
            data={
                "pub_year": "2026",
                "issn_print": "1234-5678",
                "fpage": "10",
            },
            article_titles=[],
            surnames=None,
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        qbuilder.validate_input_data()  # não deve levantar

    def test_passes_when_textual_data_present(self):
        adapter = make_xml_adapter(
            data={"pub_year": "2026", "issn_electronic": "0000-1111"},
            article_titles=["Título do artigo"],
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        qbuilder.validate_input_data()  # não deve levantar

    def test_passes_when_only_surnames_present(self):
        adapter = make_xml_adapter(
            data={"pub_year": "2026", "issn_electronic": "0000-1111"},
            surnames="Silva",
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        qbuilder.validate_input_data()  # não deve levantar

    def test_raises_not_enough_parameters_when_all_empty(self):
        adapter = make_xml_adapter(
            data={"pub_year": "2026", "issn_electronic": "0000-1111"},
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        with self.assertRaises(exceptions.NotEnoughParametersToGetPidProviderXMLError):
            qbuilder.validate_input_data()

    def test_raises_not_enough_parameters_when_titles_are_blank(self):
        """Lista de títulos só com valores falsy deve ser tratada como vazia."""
        adapter = make_xml_adapter(
            data={"pub_year": "2026", "issn_electronic": "0000-1111"},
            article_titles=["", None],
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        with self.assertRaises(exceptions.NotEnoughParametersToGetPidProviderXMLError):
            qbuilder.validate_input_data()


class PkgNameListTests(SimpleTestCase):

    def test_combines_all_sources_and_drops_falsy(self):
        adapter = make_xml_adapter(
            data={},
            pkg_name="pkg-a",
            sps_pkg_name="pkg-b",
            deprecated_sps_pkg_name_list=["pkg-c", "", None, "pkg-a"],
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        self.assertEqual(qbuilder.pkg_name_list, {"pkg-a", "pkg-b", "pkg-c"})

    def test_empty_when_no_names_available(self):
        adapter = make_xml_adapter(data={}, pkg_name=None, sps_pkg_name=None)
        qbuilder = QueryBuilderPidProviderXML(adapter)
        self.assertEqual(qbuilder.pkg_name_list, set())


class IdentifierQueriesTests(SimpleTestCase):

    def test_empty_when_nothing_set(self):
        adapter = make_xml_adapter(data={})
        qbuilder = QueryBuilderPidProviderXML(adapter)
        self.assertEqual(qbuilder.identifier_queries, Q())

    def test_v3_only(self):
        adapter = make_xml_adapter(data={}, v3="V3-123")
        qbuilder = QueryBuilderPidProviderXML(adapter)
        self.assertEqual(qbuilder.identifier_queries, Q(v3="V3-123"))

    def test_v2_and_aop_pid_combine_with_or(self):
        adapter = make_xml_adapter(data={}, v2="V2-1", aop_pid="AOP-1")
        qbuilder = QueryBuilderPidProviderXML(adapter)
        expected = Q(v2="V2-1") | (Q(v2="AOP-1") | Q(aop_pid="AOP-1"))
        self.assertEqual(qbuilder.identifier_queries, expected)

    def test_includes_pkg_names_and_main_doi(self):
        adapter = make_xml_adapter(
            data={"main_doi": "10.1234/xyz"},
            pkg_name="pkg-a",
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        expected = Q(pkg_name__in={"pkg-a"}) | Q(main_doi="10.1234/xyz")
        self.assertEqual(qbuilder.identifier_queries, expected)


class IssnQueryTests(SimpleTestCase):

    def test_raises_when_no_issn(self):
        adapter = make_xml_adapter(data={})
        qbuilder = QueryBuilderPidProviderXML(adapter)
        with self.assertRaises(exceptions.RequiredISSNErrorToGetPidProviderXMLError):
            qbuilder.issn_query

    def test_electronic_only(self):
        adapter = make_xml_adapter(data={"issn_electronic": "0000-1111"})
        qbuilder = QueryBuilderPidProviderXML(adapter)
        self.assertEqual(qbuilder.issn_query, Q(issn_electronic="0000-1111"))

    def test_print_only(self):
        adapter = make_xml_adapter(data={"issn_print": "1234-5678"})
        qbuilder = QueryBuilderPidProviderXML(adapter)
        self.assertEqual(qbuilder.issn_query, Q(issn_print="1234-5678"))

    def test_both_issn_combine_with_or(self):
        adapter = make_xml_adapter(
            data={"issn_electronic": "0000-1111", "issn_print": "1234-5678"}
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        expected = Q(issn_electronic="0000-1111") | Q(issn_print="1234-5678")
        self.assertEqual(qbuilder.issn_query, expected)


class IssueParamsTests(SimpleTestCase):

    def test_returns_expected_keys(self):
        adapter = make_xml_adapter(
            data={"pub_year": "2026", "volume": "10", "number": "2", "suppl": "1"}
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        self.assertEqual(
            qbuilder.issue_params,
            {"pub_year": "2026", "volume": "10", "number": "2", "suppl": "1"},
        )

    def test_missing_values_are_none(self):
        adapter = make_xml_adapter(data={})
        qbuilder = QueryBuilderPidProviderXML(adapter)
        self.assertEqual(
            qbuilder.issue_params,
            {"pub_year": None, "volume": None, "number": None, "suppl": None},
        )


class ArticleLocationParamsTests(SimpleTestCase):

    def test_without_order(self):
        adapter = make_xml_adapter(
            data={"elocation_id": "e123", "fpage": "10", "lpage": "20"},
            order=None,
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        params = qbuilder.article_location_params
        self.assertEqual(
            params,
            {
                "elocation_id": "e123",
                "fpage": "10",
                "fpage_seq": None,
                "lpage": "20",
            },
        )
        self.assertNotIn("v2__endswith", params)

    def test_with_order_adds_v2_endswith(self):
        adapter = make_xml_adapter(data={}, order="00003")
        qbuilder = QueryBuilderPidProviderXML(adapter)
        params = qbuilder.article_location_params
        self.assertEqual(params["v2__endswith"], "00003")


class ArticleDataQueryTests(SimpleTestCase):
    """
    Atualizado: `article_data_query` não tem mais o branch OR nem faz o
    merge com `article_location_params` internamente. Agora ela sempre
    retorna a query AND com os valores reais (truthy ou não) dos 4 campos
    textuais. A junção com localização/fascículo passou para
    `get_article_data_query`.
    """

    def test_returns_and_query_with_available_textual_fields(self):
        adapter = make_xml_adapter(
            data={"z_surnames": "Silva", "z_partial_body": "corpo"}
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        expected = Q(
            z_surnames="Silva", z_collab=None, z_links=None, z_partial_body="corpo"
        )
        self.assertEqual(qbuilder.article_data_query, expected)

    def test_does_not_use_or_even_when_multiple_fields_present(self):
        """Antes do diff, múltiplos campos truthy geravam OR; agora é sempre AND."""
        adapter = make_xml_adapter(
            data={
                "z_surnames": "Silva",
                "z_collab": "Grupo X",
                "z_links": "link1",
                "z_partial_body": "corpo",
            }
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        expected = Q(
            z_surnames="Silva",
            z_collab="Grupo X",
            z_links="link1",
            z_partial_body="corpo",
        )
        self.assertEqual(qbuilder.article_data_query, expected)
        # Garante que não é a versão OR (equivalente mas com | em vez de AND
        # implícito do Q com múltiplos kwargs)
        or_version = (
            Q(z_surnames="Silva")
            | Q(z_collab="Grupo X")
            | Q(z_links="link1")
            | Q(z_partial_body="corpo")
        )
        self.assertNotEqual(qbuilder.article_data_query, or_version)

    def test_returns_and_query_when_no_textual_data(self):
        adapter = make_xml_adapter(data={})
        qbuilder = QueryBuilderPidProviderXML(adapter)
        expected = Q(z_surnames=None, z_collab=None, z_links=None, z_partial_body=None)
        self.assertEqual(qbuilder.article_data_query, expected)

    def test_no_longer_merges_with_article_location_params(self):
        """
        Regressão: antes do diff, quando não havia dado textual,
        `article_data_query` retornava `Q(...) & Q(**article_location_params)`.
        Agora essa junção não ocorre mais aqui.
        """
        adapter = make_xml_adapter(
            data={"elocation_id": "e123", "fpage": "10", "lpage": "20"}
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        old_style_expected = Q(
            z_surnames=None, z_collab=None, z_links=None, z_partial_body=None
        ) & Q(**qbuilder.article_location_params)
        self.assertNotEqual(qbuilder.article_data_query, old_style_expected)


class GetArticleDataQueryTests(SimpleTestCase):
    """Novo método introduzido pelo diff, usado em select_records (models.py)."""

    def test_issue_true_combines_article_data_issue_and_location_params(self):
        adapter = make_xml_adapter(
            data={
                "z_surnames": "Silva",
                "pub_year": "2026",
                "volume": "10",
                "number": "2",
                "suppl": None,
                "elocation_id": "e1",
                "fpage": "10",
                "lpage": "20",
            }
        )
        qbuilder = QueryBuilderPidProviderXML(adapter)
        result = qbuilder.get_article_data_query(issue=True)
        expected = (
            qbuilder.article_data_query
            & Q(**qbuilder.issue_params)
            & Q(**qbuilder.article_location_params)
        )
        self.assertEqual(result, expected)

    def test_issue_false_requires_issue_and_location_fields_null(self):
        adapter = make_xml_adapter(data={"z_surnames": "Silva"})
        qbuilder = QueryBuilderPidProviderXML(adapter)
        result = qbuilder.get_article_data_query(issue=False)
        expected = qbuilder.article_data_query & Q(
            volume__isnull=True,
            number__isnull=True,
            suppl__isnull=True,
            elocation_id__isnull=True,
            fpage__isnull=True,
            lpage__isnull=True,
        )
        self.assertEqual(result, expected)

    def test_issue_true_and_false_produce_different_queries(self):
        adapter = make_xml_adapter(data={"z_surnames": "Silva", "pub_year": "2026"})
        qbuilder = QueryBuilderPidProviderXML(adapter)
        self.assertNotEqual(
            qbuilder.get_article_data_query(issue=True),
            qbuilder.get_article_data_query(issue=False),
        )


class ZeroToNoneTests(SimpleTestCase):

    def test_returns_none_for_falsy_input(self):
        self.assertIsNone(zero_to_none(None))
        self.assertIsNone(zero_to_none(""))

    def test_returns_none_when_digit_zero(self):
        self.assertIsNone(zero_to_none("0"))

    def test_returns_data_when_non_digit(self):
        self.assertEqual(zero_to_none("abc"), "abc")

    def test_returns_data_when_digit_nonzero(self):
        self.assertEqual(zero_to_none("5"), "5")


class GetScoreTests(SimpleTestCase):

    def test_equal_and_truthy_returns_max(self):
        self.assertEqual(get_score("a", "a", min_value=0, max_value=10), 10)

    def test_equal_and_falsy_returns_min(self):
        self.assertEqual(get_score(None, None, min_value=1, max_value=10), 1)

    def test_different_returns_zero(self):
        self.assertEqual(get_score("a", "b", min_value=0, max_value=10), 0)


class CompareListsTests(SimpleTestCase):

    def test_identical_lists_return_one(self):
        self.assertEqual(compare_lists(["a", "b"], ["a", "b"]), 1)

    def test_empty_xml_adapter_titles_returns_zero(self):
        self.assertEqual(compare_lists(["a"], []), 0)

    def test_empty_registered_returns_zero(self):
        self.assertEqual(compare_lists([], ["a"]), 0)

    @patch("pid_provider.query_params.how_similar")
    def test_delegates_to_how_similar_when_different(self, mock_how_similar):
        mock_how_similar.return_value = 0.75
        result = compare_lists(["Título Um"], ["Titulo Dois"])
        self.assertEqual(result, 0.75)
        mock_how_similar.assert_called_once()


class CompareItemsTests(SimpleTestCase):

    def test_list_field_uses_compare_lists(self):
        result = compare_items("titles", ["a", "b"], ["a", "b"])
        self.assertEqual(result, {"label": "titles", "score": 1})

    def test_equal_scalars_score_one_without_registered_key(self):
        result = compare_items("z_surnames", "Silva", "Silva")
        self.assertEqual(result, {"label": "z_surnames", "score": 1})

    def test_none_and_falsy_are_treated_as_equal(self):
        result = compare_items("z_collab", None, "")
        self.assertEqual(result, {"label": "z_collab", "score": 1})

    @patch("pid_provider.query_params.how_similar")
    def test_different_scalars_uses_how_similar_and_includes_registered(
        self, mock_how_similar
    ):
        mock_how_similar.return_value = 0.4
        result = compare_items("z_surnames", "Silva", "Souza")
        self.assertEqual(
            result, {"label": "z_surnames", "score": 0.4, "registered": "Silva"}
        )
        mock_how_similar.assert_called_once_with("Souza", "Silva")

    @patch("pid_provider.query_params.how_similar")
    def test_none_input_data_falls_back_to_empty_string_for_how_similar(
        self, mock_how_similar
    ):
        """
        Regressão do diff: antes, `how_similar(input_data, registered)` com
        input_data=None estourava TypeError dentro de how_similar. Agora
        `input_data or ""` evita isso.
        """
        mock_how_similar.return_value = 0.2
        result = compare_items("z_links", "algum-link", None)
        self.assertEqual(
            result, {"label": "z_links", "score": 0.2, "registered": "algum-link"}
        )
        mock_how_similar.assert_called_once_with("", "algum-link")

    @patch("pid_provider.query_params.how_similar")
    def test_none_registered_falls_back_to_empty_string_for_how_similar(
        self, mock_how_similar
    ):
        mock_how_similar.return_value = 0.3
        result = compare_items("z_links", None, "algum-link")
        self.assertEqual(result, {"label": "z_links", "score": 0.3, "registered": None})
        mock_how_similar.assert_called_once_with("algum-link", "")


class CompareTests(SimpleTestCase):

    @patch("pid_provider.query_params.how_similar")
    def test_aggregates_scores_from_all_items(self, mock_how_similar):
        mock_how_similar.return_value = 0.5
        registered_items = {"title": "Título A", "z_surnames": "Silva"}
        input_data = {"title": "Título A", "z_surnames": "Souza"}

        result = compare(registered_items, input_data)

        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["total_score"], 1.5)  # 1 (match) + 0.5 (mocked)
        self.assertEqual(result["percentual_score"], 0.75)

    def test_missing_input_key_is_treated_as_none(self):
        registered_items = {"z_collab": None}
        input_data = {}

        result = compare(registered_items, input_data)

        self.assertEqual(result["total_score"], 1)
        self.assertEqual(result["percentual_score"], 1)