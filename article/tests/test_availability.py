"""
Testes para a detecção automática de páginas desatualizadas (availability):

- ArticleCollection.is_stale()
- ArticleCollection.create_or_update_pages() (marca `updated` ao reconstruir)
- Article.create_or_update_article_collections(user, force_update=None)

Cobrem o cenário do bug: ao atualizar a WebSiteConfiguration de uma coleção,
o sistema deve perceber sozinho (sem o chamador decidir via force_update)
que as ArticleWebPage/ArticleCollection existentes estão desatualizadas e
reconstruir as URLs antes da checagem de disponibilidade.
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, PropertyMock, patch

from article.models import Article, ArticleCollection
from collection.models import Collection


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
# ArticleCollection.is_stale()
# ============================================================


class ArticleCollectionIsStaleTestCase(unittest.TestCase):
    """Testes para ArticleCollection.is_stale()."""

    def _make_art_col(self, updated, pages_exist):
        art_col = ArticleCollection()
        art_col.collection = _mock_model_instance(Collection)
        art_col.updated = updated
        patcher = patch.object(
            ArticleCollection, "pages", new_callable=PropertyMock
        )
        mock_pages = patcher.start()
        self.addCleanup(patcher.stop)
        mock_pages.return_value.exists.return_value = pages_exist
        return art_col

    def test_stale_when_no_pages_exist_yet(self):
        """Um ArticleCollection recém-criado (sem páginas) está sempre desatualizado."""
        art_col = self._make_art_col(
            updated=datetime(2024, 1, 1, tzinfo=timezone.utc), pages_exist=False
        )
        self.assertTrue(art_col.is_stale())

    @patch("article.models.WebSiteConfiguration")
    def test_stale_when_config_updated_after_last_build(self, mock_ws_config):
        """WebSiteConfiguration alterada após a última reconstrução => desatualizado."""
        mock_ws_config.objects.filter.return_value.aggregate.return_value = {
            "updated__max": datetime(2024, 6, 1, tzinfo=timezone.utc)
        }
        art_col = self._make_art_col(
            updated=datetime(2024, 1, 1, tzinfo=timezone.utc), pages_exist=True
        )

        self.assertTrue(art_col.is_stale())
        mock_ws_config.objects.filter.assert_called_once_with(
            collection=art_col.collection, enabled=True
        )

    @patch("article.models.WebSiteConfiguration")
    def test_not_stale_when_config_not_updated_since_last_build(self, mock_ws_config):
        """WebSiteConfiguration inalterada desde a última reconstrução => atualizado."""
        mock_ws_config.objects.filter.return_value.aggregate.return_value = {
            "updated__max": datetime(2023, 1, 1, tzinfo=timezone.utc)
        }
        art_col = self._make_art_col(
            updated=datetime(2024, 1, 1, tzinfo=timezone.utc), pages_exist=True
        )

        self.assertFalse(art_col.is_stale())

    @patch("article.models.WebSiteConfiguration")
    def test_not_stale_when_no_enabled_config_exists(self, mock_ws_config):
        """Nenhuma WebSiteConfiguration habilitada para a coleção => atualizado."""
        mock_ws_config.objects.filter.return_value.aggregate.return_value = {
            "updated__max": None
        }
        art_col = self._make_art_col(
            updated=datetime(2024, 1, 1, tzinfo=timezone.utc), pages_exist=True
        )

        self.assertFalse(art_col.is_stale())


# ============================================================
# ArticleCollection.create_or_update_pages()
# ============================================================


class ArticleCollectionCreateOrUpdatePagesTestCase(unittest.TestCase):
    """Testes para ArticleCollection.create_or_update_pages()."""

    @patch("article.models.WebSiteConfiguration")
    def test_bumps_updated_after_rebuilding_pages(self, mock_ws_config):
        """
        create_or_update_pages() deve marcar `updated`, para que is_stale()
        consiga detectar a próxima mudança de WebSiteConfiguration.
        """
        mock_ws_config.objects.filter.return_value = []  # sem QA/PUBLIC config

        art_col = ArticleCollection()
        art_col.article = _mock_model_instance(Article)
        art_col.collection = _mock_model_instance(Collection)
        art_col.save = Mock()

        with patch.object(
            ArticleCollection, "classic_website", new_callable=PropertyMock
        ) as mock_classic_website, patch.object(
            ArticleCollection, "pages", new_callable=PropertyMock
        ) as mock_pages:
            mock_classic_website.return_value = None
            mock_pages.return_value.exclude.return_value.delete.return_value = None

            art_col.create_or_update_pages(Mock())

        art_col.save.assert_called_once_with(update_fields=["updated"])


# ============================================================
# Article.create_or_update_article_collections()
# ============================================================


class ArticleCreateOrUpdateArticleCollectionsTestCase(unittest.TestCase):
    """Testes para Article.create_or_update_article_collections()."""

    def _make_article(self, has_none_url_pages=False):
        article = Mock(spec=Article)
        article.pages.filter.return_value.exists.return_value = has_none_url_pages
        journal_proc = Mock()
        journal_proc.collection = Mock(name="collection")
        article.journal.journalproc_set.all.return_value = [journal_proc]
        return article, journal_proc

    @patch("article.models.ArticleCollection")
    def test_rebuilds_pages_when_collection_is_stale(self, mock_article_collection_cls):
        """Detecta a desatualização sozinho e reconstrói sem o chamador passar force_update."""
        article, journal_proc = self._make_article()
        art_col = Mock()
        art_col.is_stale.return_value = True
        mock_article_collection_cls.get_or_create.return_value = art_col

        items = Article.create_or_update_article_collections(article, "USER")

        mock_article_collection_cls.get_or_create.assert_called_once_with(
            "USER", article, journal_proc.collection
        )
        art_col.create_or_update_pages.assert_called_once_with("USER")
        self.assertEqual(items, [art_col])

    @patch("article.models.ArticleCollection")
    def test_skips_rebuild_when_not_stale_and_not_forced(self, mock_article_collection_cls):
        """Não reconstrói quando a coleção está atualizada e force_update não foi pedido."""
        article, journal_proc = self._make_article()
        art_col = Mock()
        art_col.is_stale.return_value = False
        mock_article_collection_cls.get_or_create.return_value = art_col

        items = Article.create_or_update_article_collections(article, "USER")

        art_col.create_or_update_pages.assert_not_called()
        self.assertEqual(items, [art_col])

    @patch("article.models.ArticleCollection")
    def test_force_update_rebuilds_even_when_not_stale(self, mock_article_collection_cls):
        """force_update=True explícito continua funcionando como override manual."""
        article, journal_proc = self._make_article()
        art_col = Mock()
        art_col.is_stale.return_value = False
        mock_article_collection_cls.get_or_create.return_value = art_col

        Article.create_or_update_article_collections(article, "USER", force_update=True)

        art_col.create_or_update_pages.assert_called_once_with("USER")

    @patch("article.models.ArticleCollection")
    def test_none_url_pages_trigger_rebuild_even_when_not_stale(
        self, mock_article_collection_cls
    ):
        """Páginas existentes com URL 'None' forçam reconstrução mesmo sem is_stale()."""
        article, journal_proc = self._make_article(has_none_url_pages=True)
        art_col = Mock()
        art_col.is_stale.return_value = False
        mock_article_collection_cls.get_or_create.return_value = art_col

        Article.create_or_update_article_collections(article, "USER")

        art_col.create_or_update_pages.assert_called_once_with("USER")

    @patch("article.models.logging")
    @patch("article.models.ArticleCollection")
    def test_exception_is_logged_and_partial_items_returned(
        self, mock_article_collection_cls, mock_logging
    ):
        """Exceções ao iterar coleções são capturadas e logadas, não propagadas."""
        article, journal_proc = self._make_article()
        article.journal.journalproc_set.all.side_effect = Exception("boom")

        items = Article.create_or_update_article_collections(article, "USER")

        mock_logging.exception.assert_called_once()
        self.assertEqual(items, [])
