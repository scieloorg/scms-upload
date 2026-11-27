import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from collection.models import Collection
from migration.models import (
    IdFileRecord,
    JournalAcronIdFile,
    MigratedArticle,
    MigratedData,
)


class MigratedDataCreateOrUpdateTestCase(unittest.TestCase):
    """Test cases for MigratedData.create_or_update_migrated_data() handling of duplicates."""

    @patch("migration.models.now")
    @patch.object(MigratedData.objects, "get")
    def test_create_or_update_returns_existing_when_up_to_date(self, mock_get, mock_now):
        """Test that an existing up-to-date record is returned without changes."""
        mock_now.return_value = "2024-01-01"
        mock_obj = Mock(spec=MigratedData)
        mock_obj.is_up_to_date.return_value = True
        mock_get.return_value = mock_obj

        result = MigratedData.create_or_update_migrated_data(
            user=Mock(),
            collection=Mock(),
            pid="pid123",
            data={"key": "value"},
            isis_updated_date="20240101",
        )

        self.assertEqual(result, mock_obj)

    @patch("migration.models.now")
    @patch.object(MigratedData.objects, "filter")
    @patch.object(MigratedData.objects, "get")
    def test_create_or_update_handles_multiple_objects_returned(
        self, mock_get, mock_filter, mock_now
    ):
        """Test that duplicates are resolved by keeping the most recent and deleting others."""
        mock_now.return_value = "2024-01-01"
        mock_collection = Mock()
        mock_user = Mock()

        mock_get.side_effect = MigratedData.MultipleObjectsReturned()

        mock_recent = MagicMock(spec=MigratedData)
        mock_recent.pk = 1
        mock_recent.content_type = "article"
        mock_recent.collection = mock_collection
        mock_recent.pid = "pid123"
        mock_recent.migration_status = "TODO"
        mock_recent.data = None
        mock_recent.isis_created_date = "20240101"
        mock_recent.isis_updated_date = None

        mock_queryset = MagicMock()
        mock_ordered_qs = MagicMock()
        mock_ordered_qs.first.return_value = mock_recent
        mock_queryset.order_by.return_value = mock_ordered_qs
        mock_filter.return_value = mock_queryset

        mock_exclude_qs = MagicMock()
        mock_ordered_qs.exclude.return_value = mock_exclude_qs

        result = MigratedData.create_or_update_migrated_data(
            user=mock_user,
            collection=mock_collection,
            pid="pid123",
            data={"key": "value"},
            migration_status="TODO",
            content_type="article",
            isis_created_date="20240101",
        )

        # Verify the returned object is the most recent one
        self.assertEqual(result, mock_recent)
        # Verify duplicates were deleted via filter().exclude().delete()
        mock_filter.assert_any_call(collection=mock_collection, pid="pid123")
        mock_queryset.order_by.assert_called_with("-updated")
        mock_ordered_qs.exclude.assert_called_once_with(pk=mock_recent.pk)
        mock_exclude_qs.delete.assert_called_once()
        # Verify the most recent was kept and saved
        mock_recent.save.assert_called_once()


class JournalAcronIdFileDataTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="migration-user")
        self.collection = Collection.objects.create(
            creator=self.user,
            acron="scl",
            name="SciELO",
        )
        self.journal_id_file = JournalAcronIdFile.objects.create(
            creator=self.user,
            collection=self.collection,
            journal_acron="rsp",
            source_path="/bases-work/rsp/rsp.id",
        )

    def create_article_record(self, item_pid, todo):
        return IdFileRecord.objects.create(
            creator=self.user,
            parent=self.journal_id_file,
            item_type="article",
            item_pid=item_pid,
            data={},
            todo=todo,
        )

    def test_separates_all_issue_pids_from_pending_issue_pids(self):
        self.create_article_record("S0034-89102004000200001", todo=True)
        self.create_article_record("S0034-89102004000300001", todo=False)

        data = self.journal_id_file.data

        self.assertEqual(
            data["issue_pids"],
            ["0034-891020040002", "0034-891020040003"],
        )
        self.assertEqual(
            data["pending_issue_pids"],
            ["0034-891020040002"],
        )
        self.assertEqual(data["stats"]["total_id_file_records"], 2)
        self.assertEqual(data["stats"]["total_id_file_records_to_migrate"], 1)
        self.assertEqual(data["stats"]["total_issues"], 2)


class JournalAcronIdFileHasChangesTests(TestCase):
    def setUp(self):
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, True)
        settings_override = override_settings(MEDIA_ROOT=media_root)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.user = get_user_model().objects.create_user(username="id-file-user")
        self.collection = Collection.objects.create(
            creator=self.user, acron="scl", name="SciELO"
        )
        fd, self.source_path = tempfile.mkstemp(suffix=".id")
        os.close(fd)
        self.addCleanup(os.unlink, self.source_path)
        self.write(b"conteudo original")

        self.obj = JournalAcronIdFile.create_or_update(
            self.user, self.collection, "rsp", self.source_path
        )

    def write(self, content, mtime=None):
        with open(self.source_path, "wb") as fp:
            fp.write(content)
        if mtime is not None:
            os.utime(self.source_path, (mtime, mtime))

    def create_record(self):
        IdFileRecord.objects.create(
            creator=self.user,
            parent=self.obj,
            item_type="article",
            item_pid="S0034-89102004000200001",
            data={},
        )

    def read_completely(self):
        self.create_record()
        self.obj.mark_as_read(self.user)

    def test_create_or_update_guarda_copia_e_nao_marca_como_lido(self):
        with open(self.obj.file.path, "rb") as fp:
            self.assertEqual(fp.read(), b"conteudo original")
        self.assertIsNone(self.obj.file_size)
        self.assertEqual(self.obj.updated_by, self.user)
        self.assertTrue(self.obj.has_changes())

    def test_create_or_update_obtem_registro_existente(self):
        obj = JournalAcronIdFile.create_or_update(
            self.user, self.collection, "rsp", self.source_path
        )
        self.assertEqual(obj.pk, self.obj.pk)
        self.assertEqual(JournalAcronIdFile.objects.count(), 1)

    def test_mark_as_read_registra_tamanho_do_arquivo(self):
        self.read_completely()
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.file_size, len(b"conteudo original"))

    def test_arquivo_lido_completamente_sem_mudancas(self):
        self.read_completely()
        self.assertFalse(self.obj.has_changes())

    def test_force_update(self):
        self.read_completely()
        self.assertTrue(self.obj.has_changes(force_update=True))

    def test_tamanho_diferente(self):
        self.read_completely()
        self.write(b"conteudo alterado com outro tamanho")
        self.assertTrue(self.obj.has_changes())

    def test_mesmo_tamanho_conteudo_diferente(self):
        self.read_completely()
        self.write(b"conteudo ORIGINAL")
        self.assertTrue(self.obj.has_changes())

    def test_mesmo_conteudo_data_diferente(self):
        self.write(b"conteudo original", mtime=1_700_000_000)
        self.read_completely()
        self.write(b"conteudo original", mtime=1_700_000_100)
        self.assertFalse(self.obj.has_changes())

    def test_arquivo_alterado_durante_a_leitura_sera_lido_novamente(self):
        # a cópia foi guardada em create_or_update, antes da leitura;
        # o arquivo muda durante a leitura
        self.write(b"conteudo ORIGINAL")
        self.read_completely()
        self.assertTrue(self.obj.has_changes())

    def test_nova_execucao_com_mesmo_tamanho_e_conteudo_diferente(self):
        # fluxo real: create_or_update é chamado a cada execução, antes de
        # has_changes; não pode ocultar a mudança
        self.read_completely()
        self.write(b"conteudo ORIGINAL")
        obj = JournalAcronIdFile.create_or_update(
            self.user, self.collection, "rsp", self.source_path
        )
        self.assertTrue(obj.has_changes())
        with open(obj.file.path, "rb") as fp:
            self.assertEqual(fp.read(), b"conteudo ORIGINAL")

    def test_nova_execucao_sem_mudancas_mantem_leitura(self):
        self.read_completely()
        obj = JournalAcronIdFile.create_or_update(
            self.user, self.collection, "rsp", self.source_path
        )
        self.assertFalse(obj.has_changes())

    def test_sem_registros(self):
        self.obj.mark_as_read(self.user)
        self.assertTrue(self.obj.has_changes())

    def test_arquivo_inexistente(self):
        self.read_completely()
        os.unlink(self.source_path)
        self.addCleanup(self.write, b"")
        with self.assertRaises(FileNotFoundError):
            self.obj.has_changes()


class MigratedArticleValidPidTestCase(unittest.TestCase):
    """Test cases for MigratedArticle.valid_pid() class method.

    A PID é válido se, e somente se, tem exatamente 23 caracteres e existe
    um registro MigratedArticle correspondente no banco de dados.
    """

    PID_23 = "S0034-77442021000600036"  # exatamente 23 caracteres

    @patch("migration.models.MigratedArticle.objects")
    def test_valid_pid_length_23_exists_in_db(self, mock_objects):
        """Returns True when pid has 23 chars and exists in DB."""
        mock_objects.filter.return_value.exists.return_value = True
        self.assertTrue(MigratedArticle.valid_pid(self.PID_23))

    @patch("migration.models.MigratedArticle.objects")
    def test_invalid_pid_not_in_db(self, mock_objects):
        """Returns False when pid has 23 chars but does not exist in DB."""
        mock_objects.filter.return_value.exists.return_value = False
        self.assertFalse(MigratedArticle.valid_pid(self.PID_23))

    def test_invalid_when_pid_is_none(self):
        """Returns False when pid is None (falsy)."""
        self.assertFalse(MigratedArticle.valid_pid(None))

    def test_invalid_when_pid_is_empty(self):
        """Returns False when pid is empty string (falsy)."""
        self.assertFalse(MigratedArticle.valid_pid(""))

    def test_invalid_when_pid_too_short(self):
        """Returns False when pid has fewer than 23 chars."""
        self.assertFalse(MigratedArticle.valid_pid(self.PID_23[:-1]))  # 22 chars

    def test_invalid_when_pid_too_long(self):
        """Returns False when pid has more than 23 chars."""
        self.assertFalse(MigratedArticle.valid_pid(self.PID_23 + "0"))  # 24 chars
