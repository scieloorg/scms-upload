from unittest.mock import Mock, patch

from django.test import TestCase

from article import choices
from article.models import Article, get_data_availability_status
from article.tests.data_availability_fixtures import make_xmltree


class GetDataAvailabilityStatusTest(TestCase):
    def test_sec_specific_use(self):
        tree = make_xmltree(
            '<sec sec-type="data-availability" specific-use="data-available"/>'
        )
        self.assertEqual(choices.DAS_DATA_AVAILABLE, get_data_availability_status(tree))

    def test_fn_specific_use(self):
        tree = make_xmltree(
            '<fn-group><fn fn-type="data-availability" '
            'specific-use="data-available-upon-request"/></fn-group>'
        )
        self.assertEqual(
            choices.DAS_DATA_AVAILABLE_UPON_REQUEST,
            get_data_availability_status(tree),
        )

    def test_accepts_element(self):
        tree = make_xmltree(
            '<sec sec-type="data-availability" specific-use="data-in-article"/>'
        )
        self.assertEqual(
            choices.DAS_DATA_IN_ARTICLE, get_data_availability_status(tree.getroot())
        )

    def test_first_valid_specific_use_wins(self):
        tree = make_xmltree(
            '<sec sec-type="data-availability" specific-use="xxx"/>'
            '<sec sec-type="data-availability" specific-use="data-not-available"/>'
        )
        self.assertEqual(
            choices.DAS_DATA_NOT_AVAILABLE, get_data_availability_status(tree)
        )

    def test_absent(self):
        self.assertEqual(choices.DAS_ABSENT, get_data_availability_status(make_xmltree()))

    def test_invalid_specific_use(self):
        tree = make_xmltree('<sec sec-type="data-availability" specific-use="xxx"/>')
        self.assertEqual(choices.DAS_INVALID, get_data_availability_status(tree))

    def test_specific_use_cannot_be_internal_value(self):
        tree = make_xmltree('<sec sec-type="data-availability" specific-use="absent"/>')
        self.assertEqual(choices.DAS_INVALID, get_data_availability_status(tree))

    def test_missing_specific_use(self):
        tree = make_xmltree('<sec sec-type="data-availability"/>')
        self.assertEqual(choices.DAS_INVALID, get_data_availability_status(tree))

    def test_ignores_sub_article(self):
        tree = make_xmltree(
            sub_article=(
                '<sub-article article-type="translation"><back>'
                '<sec sec-type="data-availability" specific-use="data-available"/>'
                "</back></sub-article>"
            )
        )
        self.assertEqual(choices.DAS_ABSENT, get_data_availability_status(tree))

    def test_none(self):
        self.assertIsNone(get_data_availability_status(None))


class AddDataAvailabilityStatusTest(TestCase):
    def test_sets_status_from_xml(self):
        article = Article()
        xml_with_pre = Mock(
            xmltree=make_xmltree(
                '<sec sec-type="data-availability" specific-use="uninformed"/>'
            )
        )
        article.add_data_availability_status(xml_with_pre)
        self.assertEqual(choices.DAS_UNINFORMED, article.data_availability_status)

    def test_does_not_raise_on_error(self):
        article = Article()
        article.add_data_availability_status(Mock(xmltree=Mock()))
        self.assertIsNone(article.data_availability_status)


class UpdateDataAvailabilityStatusTest(TestCase):
    def _article(self, status=None, xmltree=None):
        article = Mock(spec=Article)
        article.data_availability_status = status
        article.sps_pkg.xml_with_pre = Mock(xmltree=xmltree) if xmltree else None
        article.add_data_availability_status = (
            lambda xml_with_pre: setattr(
                article,
                "data_availability_status",
                get_data_availability_status(xml_with_pre.xmltree),
            )
        )
        return article

    def _queryset(self, articles):
        qs = Mock()
        qs.filter.return_value = qs
        qs.iterator.return_value = iter(articles)
        return qs

    def test_updates_articles(self):
        article = self._article(xmltree=make_xmltree())
        qs = self._queryset([article])

        updated = Article.update_data_availability_status(queryset=qs)

        self.assertEqual(1, updated)
        self.assertEqual(choices.DAS_ABSENT, article.data_availability_status)
        article.save.assert_called_once_with(update_fields=["data_availability_status"])

    def test_filters_not_processed_by_default(self):
        qs = self._queryset([])
        Article.update_data_availability_status(queryset=qs)
        qs.filter.assert_any_call(sps_pkg__isnull=False)
        qs.filter.assert_any_call(data_availability_status__isnull=True)

    def test_force_update_does_not_filter_status(self):
        qs = self._queryset([])
        Article.update_data_availability_status(queryset=qs, force_update=True)
        qs.filter.assert_called_once_with(sps_pkg__isnull=False)

    def test_skips_article_without_xml(self):
        article = self._article(xmltree=None)
        updated = Article.update_data_availability_status(
            queryset=self._queryset([article])
        )
        self.assertEqual(0, updated)
        article.save.assert_not_called()

    def test_continues_after_error(self):
        broken = self._article(xmltree=make_xmltree())
        broken.save.side_effect = Exception("db error")
        ok = self._article(xmltree=make_xmltree())

        updated = Article.update_data_availability_status(
            queryset=self._queryset([broken, ok])
        )

        self.assertEqual(1, updated)
        ok.save.assert_called_once()
