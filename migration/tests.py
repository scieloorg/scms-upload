from django.test import TestCase
from .models import JournalAcronIdFile
from .models import migrated_files_directory_path, Collection, extract_relative_path
from core.users.models import User
from unittest.mock import Mock, PropertyMock
# Create your tests here.

class TestMigratedFilesDirectoryPath(TestCase):
    def setUp(self):
        self.paths = [
            "classic_website/spa/scielo_www/hercules-spa/new_platform/bases_for_upload/bases-work",
            "classic_website/spa/scielo_www/scielosp/bases/pdf",
            "classic_website/spa/scielo_www/scielosp/bases/xml",
            "classic_website/spa/scielo_www/scielosp/bases/translation",
            "classic_website/spa/scielo_www/scielosp/htdocs/img/revistas",
        ]
        self.paths_relative = [
            "bases-work",
            "bases/pdf",
            "bases/xml",
            "bases/translation",
            "htdocs/img/revistas",
        ]

    def test_extract_relative_path(self):
        for path, path_relative in zip(self.paths, self.paths_relative):
            with self.subTest(path=path):
                self.assertEqual(extract_relative_path(path), path_relative)

    def test_journal_files_directory_path_bases_work(self):
        mock_instance = Mock(spec_set=['source_path', 'collection', 'collection.acron'])
        # Garante que `source_path` está definido para ser usado no except
        for path, path_relative in zip(self.paths, self.paths_relative):
            with self.subTest(path=path):
                mock_instance.source_path = path
                mock_instance.collection.acron = "spa"
                path = migrated_files_directory_path(mock_instance, "test.xml")
                self.assertEqual(path, f"classic_website/spa/{path_relative}") # Expected path: classic_website/spa/bases-work

    def test_migrated_files_directory_path_bases_work(self):
        mock_instance = Mock(spec_set=['original_path', 'collection', 'collection.acron'])
        # Garante que `source_path` está definido para ser usado no except
        for path, path_relative in zip(self.paths, self.paths_relative):
            with self.subTest(path=path):
                mock_instance.original_path = path
                mock_instance.collection.acron = "spa"
                path = migrated_files_directory_path(mock_instance, "test.xml")
                self.assertEqual(path, f"classic_website/spa/{path_relative}")