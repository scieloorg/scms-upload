from unittest.mock import Mock, PropertyMock

from django.test import TestCase

from core.users.models import User

from .models import (
    Collection,
    JournalAcronIdFile,
    extract_relative_path,
    migrated_files_directory_path,
)

# Create your tests here.


class TestMigratedFilesDirectoryPath(TestCase):
    def setUp(self):
        # original_path or source_path
        self.paths = [
            "classic_website/spa/scielo_www/hercules-spa/new_platform/bases_for_upload/bases-work/acron/file_asdg.id",
            "classic_website/spa/scielo_www/scielosp/bases/pdf/acron/file_asdg.pdf",
            "classic_website/spa/scielo_www/scielosp/bases/xml/acron/file_asdg.xml",
            "classic_website/spa/scielo_www/scielosp/bases/translation/acron/file_asdg.xml",
            "classic_website/spa/scielo_www/scielosp/htdocs/img/revistas/acron/file_asdg.jpg",
        ]
        self.paths_relative = [
            "bases-work/acron/file_asdg.id",
            "bases/pdf/acron/file_asdg.pdf",
            "bases/xml/acron/file_asdg.xml",
            "bases/translation/acron/file_asdg.xml",
            "htdocs/img/revistas/acron/file_asdg.jpg",
        ]

    def test_extract_relative_path(self):
        for path, path_relative in zip(self.paths, self.paths_relative):
            with self.subTest(path=path):
                self.assertEqual(extract_relative_path(path), path_relative)

    def test_journal_files_directory_path_bases_work(self):
        mock_instance = Mock(spec_set=["source_path", "collection", "collection.acron"])
        # Garante que `source_path` está definido para ser usado no except
        for path, path_relative in zip(self.paths, self.paths_relative):
            with self.subTest(path=path):
                mock_instance.source_path = path
                mock_instance.collection.acron = "spa"
                path = migrated_files_directory_path(mock_instance, "test.xml")
                self.assertEqual(
                    path, f"classic_website/spa/{path_relative}"
                )  # Expected path: classic_website/spa/bases-work

    def test_migrated_files_directory_path_bases_work(self):
        mock_instance = Mock(
            spec_set=["original_path", "collection", "collection.acron"]
        )
        for path, path_relative in zip(self.paths, self.paths_relative):
            with self.subTest(path=path):
                mock_instance.original_path = path
                mock_instance.collection.acron = "spa"
                path = migrated_files_directory_path(mock_instance, "test.xml")
                self.assertEqual(path, f"classic_website/spa/{path_relative}")
