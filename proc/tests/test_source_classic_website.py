from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from migration.models import MigratedIssue
from proc import source_classic_website


def make_item(pid, date):
    item = MagicMock()
    item.pid = pid
    item.date = date
    item.data = {"pid": pid}
    return item


@patch("proc.source_classic_website.MigratedFile")
@patch("proc.source_classic_website.modified_date", return_value="2024-01-01")
class RegisterIdFileRecordsTest(TestCase):
    """
    register_id_file_records: o filtro ``since`` é a data mais recente
    (isis_updated_date) já registrada para a coleção e o content_type; o
    .id de title/issue é único por coleção.
    """

    def setUp(self):
        self.user = get_user_model().objects.create(username="u")
        self.collection = Collection.objects.create(acron="scl", creator=self.user)
        other = Collection.objects.create(acron="arg", creator=self.user)
        for collection, pid, date in [
            (self.collection, "0034-891020240001", "20240110"),
            (self.collection, "0001-371420240001", "20240105"),
            # sem data: não pode anular o filtro
            (self.collection, "0034-891020240003", None),
            # outra coleção: não é considerada
            (other, "0034-891020240009", "20260101"),
        ]:
            MigratedIssue.objects.create(
                collection=collection,
                pid=pid,
                content_type="issue",
                isis_updated_date=date,
                creator=self.user,
            )

    def _register(self, items, force_update=False, content_type="issue"):
        proc_class = MagicMock()
        id_file = MagicMock()
        id_file.items.return_value = items
        source_classic_website.register_id_file_records(
            self.user,
            self.collection,
            "/bases/issue/issue.id",
            lambda: id_file,
            proc_class,
            content_type,
            force_update,
        )
        registered = [
            call.args[2]
            for call in proc_class.register_classic_website_data.call_args_list
        ]
        return registered, id_file

    def test_since_e_a_data_mais_recente_da_colecao_ignorando_sem_data(
        self, mock_modified_date, mock_migrated_file
    ):
        mock_migrated_file.has_changes.return_value = True
        items = [make_item("0034-891020240002", "20240110")]

        registered, id_file = self._register(items)

        id_file.items.assert_called_once_with(since="20240110")
        self.assertEqual(registered, ["0034-891020240002"])
        mock_migrated_file.create_or_update.assert_called_once()

    def test_sem_registros_do_content_type_le_tudo(
        self, mock_modified_date, mock_migrated_file
    ):
        mock_migrated_file.has_changes.return_value = True

        _, id_file = self._register([], content_type="journal")

        id_file.items.assert_called_once_with(since=None)

    def test_force_update_le_tudo(self, mock_modified_date, mock_migrated_file):
        mock_migrated_file.has_changes.return_value = True

        _, id_file = self._register([], force_update=True)

        id_file.items.assert_called_once_with(since=None)

    def test_arquivo_sem_mudancas_nao_e_lido(
        self, mock_modified_date, mock_migrated_file
    ):
        mock_migrated_file.has_changes.return_value = False

        _, id_file = self._register([])

        id_file.items.assert_not_called()
        mock_migrated_file.create_or_update.assert_not_called()

    def test_leitura_interrompida_nao_marca_como_lido(
        self, mock_modified_date, mock_migrated_file
    ):
        mock_migrated_file.has_changes.return_value = True

        def items(since=None):
            yield make_item("0034-891020240002", "20240110")
            raise OSError("interrompido")

        proc_class = MagicMock()
        id_file = MagicMock()
        id_file.items.side_effect = items
        with patch("proc.source_classic_website.UnexpectedEvent") as mock_event:
            source_classic_website.register_id_file_records(
                self.user,
                self.collection,
                "/bases/issue/issue.id",
                lambda: id_file,
                proc_class,
                "issue",
                False,
            )

        # o registro lido antes da interrupção é registrado
        proc_class.register_classic_website_data.assert_called_once()
        # o arquivo será lido novamente na próxima execução
        mock_migrated_file.create_or_update.assert_not_called()
        mock_event.create.assert_called_once()

    def test_falha_em_registro_individual_marca_como_lido(
        self, mock_modified_date, mock_migrated_file
    ):
        mock_migrated_file.has_changes.return_value = True
        proc_class = MagicMock()
        proc_class.register_classic_website_data.side_effect = [
            ValueError("registro invalido"),
            None,
        ]
        id_file = MagicMock()
        id_file.items.return_value = [
            make_item("0034-891020240002", "20240110"),
            make_item("0034-891020240004", "20240111"),
        ]
        with patch("proc.source_classic_website.UnexpectedEvent") as mock_event:
            source_classic_website.register_id_file_records(
                self.user,
                self.collection,
                "/bases/issue/issue.id",
                lambda: id_file,
                proc_class,
                "issue",
                False,
            )

        self.assertEqual(proc_class.register_classic_website_data.call_count, 2)
        mock_event.create.assert_called_once()
        mock_migrated_file.create_or_update.assert_called_once()


@patch("proc.source_classic_website.register_id_file_records")
class CreateOrUpdateMigratedTest(TestCase):
    """Os chamadores passam o método (sem chamá-lo) e a classe do proc."""

    def test_journal(self, mock_register):
        classic_website = MagicMock()

        source_classic_website.create_or_update_migrated_journal(
            "user", "collection", classic_website, True
        )

        mock_register.assert_called_once_with(
            "user",
            "collection",
            classic_website.classic_website_paths.title_path,
            classic_website.get_journals_id_file,
            source_classic_website.JournalProc,
            "journal",
            True,
        )

    def test_issue(self, mock_register):
        classic_website = MagicMock()

        source_classic_website.create_or_update_migrated_issue(
            "user", "collection", classic_website, False
        )

        mock_register.assert_called_once_with(
            "user",
            "collection",
            classic_website.classic_website_paths.issue_path,
            classic_website.get_issues_id_file,
            source_classic_website.IssueProc,
            "issue",
            False,
        )


@patch("proc.source_classic_website.MigratedFile")
@patch("proc.source_classic_website.modified_date", return_value="2024-01-01")
class RegisterIdFileRecordsGetIdFileTest(TestCase):
    """get_id_file é chamado (get_id_file()), não usado como o próprio id file."""

    def test_get_id_file_e_chamado(self, mock_modified_date, mock_migrated_file):
        mock_migrated_file.has_changes.return_value = True

        class FakeIdFile:
            def items(self, since=None):
                return [make_item("0034-8910", "20240110")]

        class FakeClassicWebsite:
            def get_journals_id_file(self):
                return FakeIdFile()

        user = get_user_model().objects.create(username="u2")
        collection = Collection.objects.create(acron="xyz", creator=user)
        proc_class = MagicMock()
        with patch("proc.source_classic_website.UnexpectedEvent") as mock_event:
            source_classic_website.register_id_file_records(
                user,
                collection,
                "/bases/title/title.id",
                FakeClassicWebsite().get_journals_id_file,
                proc_class,
                "journal",
                False,
            )

        mock_event.create.assert_not_called()
        proc_class.register_classic_website_data.assert_called_once_with(
            user, collection, "0034-8910", {"pid": "0034-8910"}, "journal", False
        )
        mock_migrated_file.create_or_update.assert_called_once()
