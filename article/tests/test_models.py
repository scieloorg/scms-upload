"""
- Article.get(pid_v2=None, sps_pkg_name=None, pid_v3=None, sps_pkg=None)
- Article.delete_related_items(qs)
- Article.create_or_update(user, sps_pkg, issue=None, journal=None, position=None)
- Article.get_repeated_values(field_name, queryset=None, issue=None)
- Article.exclude_invalid_records(user, issue, timeout=None)
- Article._exclude_invalid_records(user, issue, timeout=None)
- Article.duplicated_item_to_keep(user, timeout, duplicated_items)

"""

import unittest
from unittest.mock import DEFAULT, MagicMock, Mock, patch

from django.contrib.auth import get_user_model

from article.models import Article
from issue.models import Issue
from journal.models import Journal
from package.models import SPSPkg

User = get_user_model()


def _mock_model_instance(model_cls, **attrs):
    """Cria um Mock(spec=model_cls) utilizável em assignments de ForeignKey.

    O ForwardManyToOneDescriptor do Django, ao fazer `obj.campo_fk = valor`,
    consulta o db router, que acessa `valor._state.db`. `_state` é um
    atributo de INSTÂNCIA (criado em Model.__init__), não de classe — por
    isso não aparece no spec de `Mock(spec=ModelClass)`, e a leitura de
    `mock._state` levanta AttributeError. Aqui atribuímos um `_state` fake
    manualmente (escrita de atributo novo é permitida com `spec` simples,
    só a leitura de atributos fora do spec é bloqueada).
    """
    mock_obj = Mock(spec=model_cls)
    mock_obj._state = Mock(db=None)
    for key, value in attrs.items():
        setattr(mock_obj, key, value)
    return mock_obj


# ============================================================
# Article.get()
# ============================================================


class ArticleGetTestCase(unittest.TestCase):
    """Testes para Article.get().

    get() delega para cls.objects.get(**params) e NÃO trata duplicidade —
    esse tratamento (MultipleObjectsReturned) é responsabilidade de quem
    chama, como create_or_update().
    """

    def test_raises_value_error_without_any_param(self):
        with self.assertRaises(ValueError):
            Article.get()

    @patch("article.models.Article.objects")
    def test_get_by_pid_v3(self, mock_objects):
        mock_article = Mock(spec=Article)
        mock_objects.get.return_value = mock_article

        result = Article.get(pid_v3="pid123")

        self.assertEqual(result, mock_article)
        mock_objects.get.assert_called_once_with(pid_v3="pid123")

    @patch("article.models.Article.objects")
    def test_get_by_pid_v2(self, mock_objects):
        mock_article = Mock(spec=Article)
        mock_objects.get.return_value = mock_article

        result = Article.get(pid_v2="pid_v2_value")

        self.assertEqual(result, mock_article)
        mock_objects.get.assert_called_once_with(pid_v2="pid_v2_value")

    @patch("article.models.Article.objects")
    def test_get_by_sps_pkg_name(self, mock_objects):
        mock_article = Mock(spec=Article)
        mock_objects.get.return_value = mock_article

        result = Article.get(sps_pkg_name="pkg-v01")

        self.assertEqual(result, mock_article)
        mock_objects.get.assert_called_once_with(sps_pkg__sps_pkg_name="pkg-v01")

    @patch("article.models.Article.objects")
    def test_get_by_sps_pkg(self, mock_objects):
        mock_sps_pkg = Mock(spec=SPSPkg)
        mock_article = Mock(spec=Article)
        mock_objects.get.return_value = mock_article

        result = Article.get(sps_pkg=mock_sps_pkg)

        self.assertEqual(result, mock_article)
        mock_objects.get.assert_called_once_with(sps_pkg=mock_sps_pkg)

    @patch("article.models.Article.objects")
    def test_get_combines_multiple_params(self, mock_objects):
        mock_article = Mock(spec=Article)
        mock_objects.get.return_value = mock_article

        Article.get(pid_v2="v2", pid_v3="v3")

        mock_objects.get.assert_called_once_with(pid_v2="v2", pid_v3="v3")

    @patch("article.models.Article.objects")
    def test_get_raises_does_not_exist(self, mock_objects):
        mock_objects.get.side_effect = Article.DoesNotExist()

        with self.assertRaises(Article.DoesNotExist):
            Article.get(pid_v3="pid123")

    @patch("article.models.Article.objects")
    def test_get_propagates_multiple_objects_returned(self, mock_objects):
        """get() não trata duplicidade — quem chama decide o que fazer."""
        mock_objects.get.side_effect = Article.MultipleObjectsReturned()

        with self.assertRaises(Article.MultipleObjectsReturned):
            Article.get(pid_v3="pid123")


# ============================================================
# Article.delete_related_items()
# ============================================================


class ArticleDeleteRelatedItemsTestCase(unittest.TestCase):
    """Testes para Article.delete_related_items()."""

    @patch("article.models.ArticleWebPage")
    @patch("article.models.ArticleCollection")
    @patch("article.models.ArticleTitle")
    @patch("article.models.ArticleDOIWithLang")
    def test_deletes_all_related_and_the_queryset_itself(
        self, mock_doi, mock_title, mock_collection, mock_webpage
    ):
        mock_qs = MagicMock()
        mock_qs.delete.return_value = (3, {})

        result = Article.delete_related_items(mock_qs)

        mock_doi.objects.filter.assert_called_once_with(article__in=mock_qs)
        mock_doi.objects.filter.return_value.delete.assert_called_once()
        mock_title.objects.filter.assert_called_once_with(parent__in=mock_qs)
        mock_title.objects.filter.return_value.delete.assert_called_once()
        mock_collection.objects.filter.assert_called_once_with(article__in=mock_qs)
        mock_collection.objects.filter.return_value.delete.assert_called_once()
        mock_webpage.objects.filter.assert_called_once_with(article__in=mock_qs)
        mock_webpage.objects.filter.return_value.delete.assert_called_once()
        mock_qs.delete.assert_called_once()
        self.assertEqual(result, (3, {}))


# ============================================================
# Article.create_or_update()
# ============================================================


class ArticleCreateOrUpdateTestCase(unittest.TestCase):

    def setUp(self):
        patcher = patch.multiple(
            Article,
            add_journal=DEFAULT,
            add_issue=DEFAULT,
            add_pages=DEFAULT,
            add_article_publication_date=DEFAULT,
            add_pp_xml=DEFAULT,
            add_sections=DEFAULT,
            add_position=DEFAULT,
            add_position_in_table_of_contents=DEFAULT,  # <-- adicionado
            add_article_titles=DEFAULT,
            add_doi_with_lang=DEFAULT,
            save=DEFAULT,
        )
        self.mocks = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_sps_pkg(self, pid_v3="pidv3", pid_v2="pidv2"):
        mock_xml_with_pre = Mock()
        mock_xml_with_pre.xmltree.find.return_value.get.return_value = "research-article"

        # obj.sps_pkg = sps_pkg também é ForeignKey — precisa de _state fake.
        mock_sps_pkg = _mock_model_instance(
            SPSPkg,
            xml_with_pre=mock_xml_with_pre,
            pid_v3=pid_v3,
            pid_v2=pid_v2,
        )
        return mock_sps_pkg, mock_xml_with_pre

    def test_raises_value_error_without_sps_pkg(self):
        with self.assertRaises(ValueError):
            Article.create_or_update(_mock_model_instance(User), None)

    def test_raises_value_error_when_xml_with_pre_missing(self):
        mock_sps_pkg = _mock_model_instance(SPSPkg, xml_with_pre=None)

        with self.assertRaises(ValueError):
            Article.create_or_update(_mock_model_instance(User), mock_sps_pkg)

    @patch.object(Article, "get")
    def test_creates_new_article_when_does_not_exist(self, mock_get):
        mock_get.side_effect = Article.DoesNotExist()
        mock_sps_pkg, mock_xml_with_pre = self._make_sps_pkg()
        mock_user = _mock_model_instance(User)

        obj = Article.create_or_update(mock_user, mock_sps_pkg)

        self.assertEqual(obj.creator, mock_user)
        self.assertEqual(obj.sps_pkg, mock_sps_pkg)
        self.assertEqual(obj.pid_v3, mock_sps_pkg.pid_v3)
        self.assertEqual(obj.pid_v2, mock_sps_pkg.pid_v2)
        self.mocks["add_journal"].assert_called_once_with(mock_xml_with_pre)
        self.mocks["add_issue"].assert_called_once_with(mock_xml_with_pre)

    @patch.object(Article, "get")
    def test_add_sections_receives_xml_with_pre(self, mock_get):
        mock_get.side_effect = Article.DoesNotExist()
        mock_sps_pkg, mock_xml_with_pre = self._make_sps_pkg()
        mock_user = _mock_model_instance(User)

        Article.create_or_update(mock_user, mock_sps_pkg)

        self.mocks["add_sections"].assert_called_once_with(mock_user, mock_xml_with_pre)

    @patch.object(Article, "get")
    def test_add_position_runs_before_add_sections(self, mock_get):
        """
        No fluxo atual, add_position() roda ANTES do primeiro save()
        (junto com add_pages/add_pp_xml, ainda a partir de `position`/
        `xml_with_pre.fpage`). add_sections() só roda DEPOIS do save(),
        já com o Article persistido (necessário para usar `self.issue`
        e `self.sections` no cálculo de add_position_in_table_of_contents,
        que é o passo seguinte).
        """
        mock_get.side_effect = Article.DoesNotExist()
        mock_sps_pkg, mock_xml_with_pre = self._make_sps_pkg()
        mock_user = _mock_model_instance(User)

        manager = Mock()
        manager.attach_mock(self.mocks["add_position"], "add_position")
        manager.attach_mock(self.mocks["add_sections"], "add_sections")

        Article.create_or_update(mock_user, mock_sps_pkg, position=None)

        call_names = [c[0] for c in manager.mock_calls]
        self.assertLess(
            call_names.index("add_position"), call_names.index("add_sections")
        )

    @patch.object(Article, "delete_related_items")
    @patch.object(Article, "get")
    def test_deduplicates_on_multiple_objects_returned(
        self, mock_get, mock_delete_related
    ):
        mock_get.side_effect = Article.MultipleObjectsReturned()
        mock_sps_pkg, mock_xml_with_pre = self._make_sps_pkg()
        mock_user = _mock_model_instance(User)

        kept = Mock(spec=Article)
        kept.id = 1

        mock_qs = MagicMock()
        mock_qs.order_by.return_value = mock_qs
        mock_qs.first.return_value = kept
        mock_exclude_qs = MagicMock()
        mock_qs.exclude.return_value = mock_exclude_qs

        with patch("article.models.Article.objects") as mock_objects:
            mock_objects.filter.return_value = mock_qs
            result = Article.create_or_update(mock_user, mock_sps_pkg)

        self.assertEqual(result, kept)
        mock_qs.exclude.assert_called_once_with(id=1)
        mock_delete_related.assert_called_once_with(mock_exclude_qs)

    @patch.object(Article, "get")
    def test_uses_provided_journal_and_issue_instead_of_detecting_from_xml(
        self, mock_get
    ):
        mock_get.side_effect = Article.DoesNotExist()
        mock_sps_pkg, mock_xml_with_pre = self._make_sps_pkg()
        mock_user = _mock_model_instance(User)
        mock_journal = _mock_model_instance(Journal)
        mock_issue = _mock_model_instance(Issue)

        obj = Article.create_or_update(
            mock_user, mock_sps_pkg, issue=mock_issue, journal=mock_journal
        )

        self.assertEqual(obj.journal, mock_journal)
        self.assertEqual(obj.issue, mock_issue)
        self.mocks["add_journal"].assert_not_called()
        self.mocks["add_issue"].assert_not_called()


# ============================================================
# Article.get_repeated_values()
# ============================================================


class ArticleGetRepeatedValuesTestCase(unittest.TestCase):
    """Testes para Article.get_repeated_values()."""

    @patch("article.models.Article.objects")
    def test_uses_default_manager_when_no_queryset_given(self, mock_objects):
        mock_filtered = MagicMock()
        mock_objects.filter.return_value = mock_filtered
        mock_annotated = MagicMock()
        mock_filtered.values.return_value.annotate.return_value = mock_annotated
        mock_annotated.filter.return_value.values_list.return_value = ["v1", "v2"]

        result = Article.get_repeated_values("pid_v2")

        mock_objects.filter.assert_called_once_with()
        mock_filtered.values.assert_called_once_with("pid_v2")
        self.assertEqual(result, ["v1", "v2"])

    def test_uses_given_queryset(self):
        mock_qs = MagicMock()
        mock_filtered = MagicMock()
        mock_qs.filter.return_value = mock_filtered
        mock_annotated = MagicMock()
        mock_filtered.values.return_value.annotate.return_value = mock_annotated
        mock_annotated.filter.return_value.values_list.return_value = ["v1"]

        result = Article.get_repeated_values(
            "sps_pkg__sps_pkg_name", queryset=mock_qs
        )

        mock_qs.filter.assert_called_once_with()
        mock_filtered.values.assert_called_once_with("sps_pkg__sps_pkg_name")
        self.assertEqual(result, ["v1"])

    def test_filters_by_issue_when_given(self):
        mock_qs = MagicMock()
        mock_issue = Mock()
        mock_filtered = MagicMock()
        mock_qs.filter.return_value = mock_filtered
        mock_annotated = MagicMock()
        mock_filtered.values.return_value.annotate.return_value = mock_annotated
        mock_annotated.filter.return_value.values_list.return_value = []

        Article.get_repeated_values("pid_v2", queryset=mock_qs, issue=mock_issue)

        mock_qs.filter.assert_called_once_with(issue=mock_issue)


# ============================================================
# Article.exclude_invalid_records() (wrapper)
# ============================================================


class ArticleExcludeInvalidRecordsTestCase(unittest.TestCase):
    """Testes para o wrapper exclude_invalid_records()."""

    def test_wrapper_catches_exceptions(self):
        with patch.object(
            Article, "_exclude_invalid_records", side_effect=Exception("boom")
        ):
            result = Article.exclude_invalid_records(Mock(), Mock())

        self.assertIn("error", result)
        self.assertEqual(result["error"], "boom")
        self.assertIn("traceback", result)

    def test_wrapper_returns_inner_result_on_success(self):
        expected = {"total_deleted_items": 0}
        with patch.object(
            Article, "_exclude_invalid_records", return_value=expected
        ):
            result = Article.exclude_invalid_records(Mock(), Mock())

        self.assertEqual(result, expected)

    def test_wrapper_forwards_timeout_to_inner_method(self):
        with patch.object(
            Article, "_exclude_invalid_records", return_value={}
        ) as mock_inner:
            Article.exclude_invalid_records(Mock(), Mock(), timeout=30)

        mock_inner.assert_called_once()
        self.assertEqual(mock_inner.call_args[0][2], 30)


# ============================================================
# Article._exclude_invalid_records()
# ============================================================


class ArticleExcludeInvalidRecordsInternalTestCase(unittest.TestCase):
    """Testes para Article._exclude_invalid_records().

    Fluxo atual (sem sps_pkg_id_list, sem verificação de pid_v2/pp_xml):

    1. `cls.objects.filter(issue=issue)` -> queryset base "articles".
    2. `articles.filter(sps_pkg_id__isnull=True)` -> Article sem sps_pkg,
       removidos via delete_related_items; se algo foi deletado,
       "articles" é reconsultado.
    3. `cls.get_repeated_values("sps_pkg_id", articles)` -> valores de
       sps_pkg_id duplicados.
    4. Para cada valor duplicado: `articles.filter(sps_pkg_id=value)` ->
       `Article.duplicated_item_to_keep(user, timeout, lista)` decide qual
       manter; os demais são removidos via delete_related_items.
    """

    @patch.object(Article, "get_repeated_values", return_value=[])
    @patch("article.models.Article.objects")
    def test_no_missing_sps_pkg_and_no_duplicates(
        self, mock_objects, mock_get_repeated
    ):
        articles_qs = MagicMock()
        articles_qs.count.return_value = 5

        empty_qs = MagicMock()
        empty_qs.__bool__.return_value = False
        articles_qs.filter.side_effect = lambda **kw: empty_qs

        mock_objects.filter.return_value = articles_qs

        result = Article._exclude_invalid_records(Mock(), Mock())

        self.assertEqual(result["total_articles"], 5)
        self.assertEqual(result["total_deleted_items"], 0)
        self.assertEqual(result["exceptions"], [])
        self.assertEqual(result["duplicated_items"], [])
        self.assertNotIn("total_deleted_due_to_missing_sps_pkg", result)

    @patch.object(Article, "get_repeated_values", return_value=[])
    @patch.object(Article, "delete_related_items", return_value=(3, {}))
    @patch("article.models.Article.objects")
    def test_deletes_articles_missing_sps_pkg_and_requeries(
        self, mock_objects, mock_delete_related, mock_get_repeated
    ):
        first_qs = MagicMock()
        first_qs.count.return_value = 5
        to_delete_qs = MagicMock()
        to_delete_qs.__bool__.return_value = True
        first_qs.filter.side_effect = lambda **kw: to_delete_qs

        second_qs = MagicMock()
        second_qs.count.return_value = 2

        mock_objects.filter.side_effect = [first_qs, second_qs]

        result = Article._exclude_invalid_records(Mock(), Mock())

        # cls.objects.filter(issue=issue) é chamado 2x: consulta inicial e
        # reconsulta após a exclusão dos artigos sem sps_pkg.
        self.assertEqual(mock_objects.filter.call_count, 2)
        mock_delete_related.assert_called_once_with(to_delete_qs)
        self.assertEqual(result["total_articles"], 5)
        self.assertEqual(result["total_deleted_due_to_missing_sps_pkg"], 3)
        self.assertEqual(result["total_deleted_items"], 3)

    @patch.object(
        Article, "delete_related_items", side_effect=Exception("db error")
    )
    @patch.object(Article, "get_repeated_values", return_value=[])
    @patch("article.models.Article.objects")
    def test_captures_exception_when_deleting_missing_sps_pkg(
        self, mock_objects, mock_get_repeated, mock_delete_related
    ):
        articles_qs = MagicMock()
        articles_qs.count.return_value = 5
        to_delete_qs = MagicMock()
        to_delete_qs.__bool__.return_value = True
        articles_qs.filter.side_effect = lambda **kw: to_delete_qs

        mock_objects.filter.return_value = articles_qs

        result = Article._exclude_invalid_records(Mock(), Mock())

        self.assertEqual(len(result["exceptions"]), 1)
        self.assertEqual(
            result["exceptions"][0]["action"], "deleting due to missing sps_pkg"
        )
        self.assertEqual(result["total_deleted_items"], 0)
        self.assertNotIn("total_deleted_due_to_missing_sps_pkg", result)

    @patch.object(Article, "duplicated_item_to_keep")
    @patch.object(Article, "delete_related_items", return_value=(2, {}))
    @patch.object(Article, "get_repeated_values", return_value=["sps-pkg-1"])
    @patch("article.models.Article.objects")
    def test_removes_duplicated_articles_keeping_the_chosen_one(
        self, mock_objects, mock_get_repeated, mock_delete_related, mock_keep
    ):
        articles_qs = MagicMock()
        articles_qs.count.return_value = 3

        no_missing_qs = MagicMock()
        no_missing_qs.__bool__.return_value = False

        dup1, dup2 = Mock(), Mock()
        duplicados_qs = MagicMock()
        duplicados_qs.order_by.return_value = duplicados_qs
        duplicados_qs.__iter__ = Mock(return_value=iter([dup1, dup2]))
        remover_qs = MagicMock()
        duplicados_qs.exclude.return_value = remover_qs

        def filter_side_effect(**kwargs):
            if "sps_pkg_id__isnull" in kwargs:
                return no_missing_qs
            if "sps_pkg_id" in kwargs:
                return duplicados_qs
            raise AssertionError(f"filter inesperado: {kwargs}")

        articles_qs.filter.side_effect = filter_side_effect
        mock_objects.filter.return_value = articles_qs

        mock_keep.return_value = {"keep": 10, "exceptions": []}

        result = Article._exclude_invalid_records(Mock(), Mock(), timeout=30)

        mock_keep.assert_called_once()
        called_user, called_timeout, called_list = mock_keep.call_args[0]
        self.assertEqual(called_timeout, 30)
        self.assertEqual(list(called_list), [dup1, dup2])

        duplicados_qs.exclude.assert_called_once_with(id=10)
        mock_delete_related.assert_called_once_with(remover_qs)

        self.assertEqual(len(result["duplicated_items"]), 1)
        item = result["duplicated_items"][0]
        self.assertEqual(item["value"], "sps-pkg-1")
        self.assertEqual(item["total"], 2)
        self.assertEqual(item["keep"], 10)
        self.assertEqual(item["total_deleted"], 2)
        self.assertEqual(result["total_deleted_items"], 2)
        self.assertEqual(result["exceptions"], [])

    @patch.object(Article, "delete_related_items")
    @patch.object(Article, "get_repeated_values", return_value=["sps-pkg-1"])
    @patch("article.models.Article.objects")
    def test_captures_exception_during_duplicate_removal(
        self, mock_objects, mock_get_repeated, mock_delete_related
    ):
        articles_qs = MagicMock()
        articles_qs.count.return_value = 3

        no_missing_qs = MagicMock()
        no_missing_qs.__bool__.return_value = False

        def filter_side_effect(**kwargs):
            if "sps_pkg_id__isnull" in kwargs:
                return no_missing_qs
            raise Exception("boom")

        articles_qs.filter.side_effect = filter_side_effect
        mock_objects.filter.return_value = articles_qs

        result = Article._exclude_invalid_records(Mock(), Mock())

        self.assertEqual(len(result["exceptions"]), 1)
        self.assertEqual(result["exceptions"][0]["action"], "removing duplicity")
        self.assertEqual(result["exceptions"][0]["item"], "sps-pkg-1")
        mock_delete_related.assert_not_called()
        self.assertEqual(result["total_deleted_items"], 0)


if __name__ == "__main__":
    unittest.main()
