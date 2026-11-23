import logging
from unittest.mock import Mock, patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase

from htmlxml.models import HTMLXML
from migration.models import MigratedArticle

User = get_user_model()


class HTMLXMLMultipleObjectsReturnedTestCase(TestCase):
    """Test cases for HTMLXML handling of duplicate records."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@test.com",
            password="testpass123"
        )
        
    @patch('htmlxml.models.HTMLXML.objects')
    def test_get_returns_most_recent_when_duplicates_exist(self, mock_objects):
        """Test that get() returns the most recently updated record when duplicates exist."""
        # Create mock migrated article
        mock_article = Mock(spec=MigratedArticle)
        mock_article.n_paragraphs = 10
        
        # Create mock HTMLXML objects
        mock_old = Mock(spec=HTMLXML)
        mock_old.pk = 1
        mock_old.updated = "2023-01-01"
        
        mock_recent = Mock(spec=HTMLXML)
        mock_recent.pk = 2
        mock_recent.updated = "2023-12-31"
        
        # Configure mock to raise MultipleObjectsReturned on first call
        mock_objects.get.side_effect = HTMLXML.MultipleObjectsReturned()
        
        # Configure filter to return queryset mock
        mock_queryset = Mock()
        mock_queryset.order_by.return_value.first.return_value = mock_recent
        mock_objects.filter.return_value = mock_queryset
        
        # Call the method
        result = HTMLXML.get(migrated_article=mock_article)
        
        # Verify it returns the most recent
        assert result == mock_recent
        mock_objects.filter.assert_called_once_with(migrated_article=mock_article)
        mock_queryset.order_by.assert_called_once_with("-updated")

    @patch('htmlxml.models.logging')
    def test_create_or_update_cleans_up_duplicates(self, mock_logging):
        """Test that create_or_update() deletes duplicate records."""
        # Create a real migrated article (or mock if dependencies are complex)
        mock_article = Mock(spec=MigratedArticle)
        mock_article.n_paragraphs = 10
        
        # Create first HTMLXML record
        with patch.object(HTMLXML, 'get') as mock_get, \
             patch.object(HTMLXML.objects, 'filter') as mock_filter:
            
            # Mock the main object
            mock_obj = Mock(spec=HTMLXML)
            mock_obj.pk = 1
            mock_obj.html2xml_status = 'TODO'
            mock_obj.quality = 'NOT_EVALUATED'
            mock_obj.n_references = 0
            mock_obj.record_types = None
            mock_obj.save = Mock()
            mock_get.return_value = mock_obj
            
            # Mock duplicates
            mock_duplicate1 = Mock(spec=HTMLXML)
            mock_duplicate1.pk = 2
            mock_duplicate2 = Mock(spec=HTMLXML)
            mock_duplicate2.pk = 3
            
            mock_duplicates = Mock()
            mock_duplicates.exists.return_value = True
            mock_duplicates.count.return_value = 2
            mock_duplicates.delete = Mock()
            
            mock_queryset = Mock()
            mock_queryset.exclude.return_value = mock_duplicates
            mock_filter.return_value = mock_queryset
            
            # Call create_or_update
            result = HTMLXML.create_or_update(
                user=self.user,
                migrated_article=mock_article
            )
            
            # Verify duplicates were deleted
            mock_duplicates.delete.assert_called_once()
            mock_logging.warning.assert_called()
            
            # Verify the object was saved
            mock_obj.save.assert_called_once()

    def test_get_raises_value_error_without_migrated_article(self):
        """Test that get() raises ValueError when migrated_article is not provided."""
        with self.assertRaises(ValueError) as context:
            HTMLXML.get()
        
        assert "HTMLXML.get requires migrated_article" in str(context.exception)

    def test_get_raises_does_not_exist_when_no_record_found(self):
        """Test that get() raises DoesNotExist when no record is found."""
        mock_article = MagicMock(spec=MigratedArticle)
        mock_article._meta = MigratedArticle._meta  # Pass Django model compatibility check
        
        with self.assertRaises(HTMLXML.DoesNotExist):
            HTMLXML.get(migrated_article=mock_article)


BODY_EXCEPTION = {
    "action": "Convert HTML to XML - step 3 failed convert_html_to_xml_step_30_embed_html",
    "type": "<class 'lxml.etree.XMLSyntaxError'>",
    "message": "lxml.etree.XMLSyntaxError: error parsing attribute name",
    "detail": None,
}
CITATION_EXCEPTION = {
    "action": "Processing citation 2",
    "type": "KeyError",
    "message": "KeyError: 'v30'",
    "detail": {"i": 2},
}


class FakeDocument:
    """
    Imita ``scielo_classic_website...Document``: a mesma lista
    ``exceptions`` recebe as exceções do body e as do XML completo.
    """

    def __init__(self, body_exceptions=(), xml_exceptions=(), xml=b"<article/>", raises=None):
        self.exceptions = None
        self.xml_body_and_back = ["<article><body/></article>", "<article><body/></article>"]
        self._body_exceptions = list(body_exceptions)
        self._xml_exceptions = list(xml_exceptions)
        self._xml = xml
        self._raises = raises

    def _add(self, items):
        for item in items:
            if not self.exceptions:
                self.exceptions = []
            self.exceptions.append(item)

    def generate_body_and_back_from_html(self, translations):
        self._add(self._body_exceptions)

    def generate_full_xml(self, selected_xml_body=None):
        self._add(self._xml_exceptions)
        if self._raises:
            raise self._raises
        return self._xml


class HTMLXMLExceptionsTestCase(TestCase):
    """As exceções da conversão ficam todas registradas em ``detail``."""

    def setUp(self):
        self.obj = HTMLXML()
        for name in ("save", "save_file", "save_bb_init_file", "_save_zip"):
            patcher = patch.object(HTMLXML, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, document):
        article_proc = MagicMock()
        article_proc.translations = {}
        article_proc.renditions = []
        article_proc.pkg_name = "a01"
        op = article_proc.start.return_value
        with patch("htmlxml.models.Document", return_value=document), patch.object(
            HTMLXML, "generate_report", return_value="<html/>"
        ):
            detail = self.obj.html_to_xml(MagicMock(), article_proc)
        return detail, op.finish.call_args.kwargs

    def test_xml_exceptions_are_kept_when_xml_is_created(self):
        detail, finish = self._run(FakeDocument(xml_exceptions=[CITATION_EXCEPTION]))
        self.assertEqual(detail["exceptions"], [CITATION_EXCEPTION])
        self.assertEqual(detail["xml_exceptions"], [CITATION_EXCEPTION])
        self.assertTrue(detail["xml_created"])
        self.assertEqual(detail["status"], "PENDING")
        self.assertEqual(self.obj.html2xml_status, "PENDING")
        self.assertTrue(finish["completed"])

    def test_body_and_xml_exceptions_are_not_mixed_nor_duplicated(self):
        detail, _ = self._run(
            FakeDocument(body_exceptions=[BODY_EXCEPTION], xml_exceptions=[CITATION_EXCEPTION])
        )
        self.assertEqual(detail["body_and_back_exceptions"], [BODY_EXCEPTION])
        self.assertEqual(detail["xml_exceptions"], [CITATION_EXCEPTION])
        self.assertEqual(detail["exceptions"], [BODY_EXCEPTION, CITATION_EXCEPTION])
        self.assertEqual(detail["status"], "PENDING")

    def test_failed_body_step_makes_conversion_pending(self):
        detail, _ = self._run(FakeDocument(body_exceptions=[BODY_EXCEPTION]))
        self.assertEqual(detail["exceptions"], [BODY_EXCEPTION])
        self.assertNotIn("xml_exceptions", detail)
        self.assertEqual(detail["status"], "PENDING")

    def test_without_exceptions_is_done(self):
        detail, _ = self._run(FakeDocument())
        self.assertEqual(detail["exceptions"], [])
        self.assertEqual(detail["status"], "DONE")

    def test_no_xml_keeps_only_new_exceptions(self):
        detail, finish = self._run(
            FakeDocument(body_exceptions=[BODY_EXCEPTION], xml_exceptions=[CITATION_EXCEPTION], xml=None)
        )
        self.assertEqual(detail["exceptions"], [BODY_EXCEPTION, CITATION_EXCEPTION])
        self.assertNotIn("xml_created", detail)
        self.assertFalse(finish["completed"])

    def test_exceptions_recorded_before_full_xml_fails_are_kept(self):
        detail, finish = self._run(
            FakeDocument(xml_exceptions=[CITATION_EXCEPTION], raises=ValueError("boom"))
        )
        self.assertEqual(detail["xml_exceptions"], [CITATION_EXCEPTION])
        self.assertEqual(self.obj.html2xml_status, "BLOCKED")
        self.assertIn("ValueError: boom", finish["exception"])
