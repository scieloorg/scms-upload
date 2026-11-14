# -*- coding: utf-8 -*-
"""
Testes unitários para migration/controller.py

Estratégia:
- Todas as dependências externas (models Django, classic_ws, packtools,
  tracker, etc.) são substituídas por mocks via unittest.mock.patch, para
  que os testes rodem sem banco de dados e sem o ambiente Django completo.
- Cada função pública do módulo tem pelo menos um teste de "caminho feliz"
  e, quando a função tem múltiplos blocos try/except, testes cobrindo os
  principais caminhos de erro (para garantir que a exceção certa é
  propagada e que journal_proc_event.finish/detail recebem os dados
  esperados).

IMPORTANTE: ajuste o valor de MODULE abaixo se o caminho de import real do
módulo for diferente de "migration.controller" no seu projeto.
"""

import unittest
from unittest import mock
from unittest.mock import MagicMock, call, patch

from django.utils import translation

from migration import controller as migration_controller

MODULE = "migration.controller"


class FakeClassicWebsiteJournal:
    """Objeto simples para simular classic_ws.Journal(journal_data)."""

    def __init__(self, **kwargs):
        self.first_year = kwargs.get("first_year", "20200101")
        self.electronic_issn = kwargs.get("electronic_issn", "1234-5678")
        self.print_issn = kwargs.get("print_issn", "")
        self.title = kwargs.get("title", "Revista Teste")
        self.title_iso = kwargs.get("title_iso", "Rev. Teste")
        self.previous_title = kwargs.get("previous_title", None)
        self.next_title = kwargs.get("next_title", None)
        self.abbreviated_title = kwargs.get("abbreviated_title", "Rev. T.")
        self.acronym = kwargs.get("acronym", "rt")
        self.permissions = kwargs.get("permissions", "by")
        self.title_nlm = kwargs.get("title_nlm", None)
        self.raw_publisher_names = kwargs.get(
            "raw_publisher_names", ["Editora Teste"]
        )
        self.publisher_city = kwargs.get("publisher_city", "São Paulo")
        self.publisher_state = kwargs.get("publisher_state", "SP")
        self.publisher_country = kwargs.get("publisher_country", "BR")
        self.publisher_address = kwargs.get(
            "publisher_address", ["Rua Teste, 123"]
        )
        self.publisher_email = kwargs.get("publisher_email", "contato@teste.org")
        self.wos_subject_areas = kwargs.get("wos_subject_areas", [])
        self.mission = kwargs.get(
            "mission", [{"language": "pt", "text": "Missão da revista"}]
        )
        self.subject_areas = kwargs.get("subject_areas", ["HEALTH SCIENCES"])
        self.status_history = kwargs.get("status_history", [])
        self.current_status = kwargs.get("current_status", "C")


# ===========================================================================
# check_component_type
# ===========================================================================
class CheckComponentTypeTests(unittest.TestCase):

    def test_pdf_sem_lang_retorna_rendition(self):
        file = {"type": "pdf", "name": "artigo.pdf", "key": "artigo"}
        self.assertEqual(migration_controller.check_component_type(file), "rendition")

    def test_pdf_com_lang_prefixo_removido_retorna_rendition(self):
        file = {"type": "pdf", "name": "en_artigo.pdf", "lang": "en", "key": "artigo"}
        # remove "en_" -> "artigo.pdf" != ".pdf" -> não é rendition puro
        self.assertEqual(migration_controller.check_component_type(file), "rendition")

    def test_pdf_com_key_igual_ao_restante_retorna_rendition(self):
        file = {"type": "pdf", "name": "en_chave.pdf", "lang": "en", "key": "artigo.pdf"}
        # remove "en_" -> "chave.pdf"; remove key "chave.pdf" -> ""
        # "" != ".pdf" -> supplmat (comportamento atual do código)
        self.assertEqual(migration_controller.check_component_type(file), "supplmat")

    def test_tipo_nao_pdf_retorna_o_proprio_tipo(self):
        file = {"type": "xml", "name": "artigo.xml"}
        self.assertEqual(migration_controller.check_component_type(file), "xml")

    def test_pdf_sem_chaves_lang_key_nao_quebra(self):
        file = {"type": "pdf", "name": ".pdf"}
        self.assertEqual(migration_controller.check_component_type(file), "rendition")


# ===========================================================================
# create_journal_history
# ===========================================================================
class CreateJournalHistoryTests(unittest.TestCase):
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    @patch("migration.controller.JournalHistory")
    @patch("migration.controller.parse_yyyymmdd")
    def test_status_d_gera_interrupted_com_motivo_ceased(
        self, mock_parse, mock_journal_history
    ):
        mock_parse.return_value = (2021, 5, 10)
        user = MagicMock()
        jc = MagicMock()
        classic_website_journal = FakeClassicWebsiteJournal(
            status_history=[{"date": "20210510", "status": "D", "reason": "outro motivo"}]
        )

        migration_controller.create_journal_history(user, jc, classic_website_journal)

        mock_journal_history.create_or_update.assert_called_once_with(
            user, jc, "INTERRUPTED", 2021, 5, 10, "ceased"
        )

    @patch("migration.controller.JournalHistory")
    @patch("migration.controller.parse_yyyymmdd")
    def test_status_c_gera_admitted(self, mock_parse, mock_journal_history):
        mock_parse.return_value = (2019, 1, 1)
        user = MagicMock()
        jc = MagicMock()
        classic_website_journal = FakeClassicWebsiteJournal(
            status_history=[{"date": "20190101", "status": "C", "reason": None}]
        )

        migration_controller.create_journal_history(user, jc, classic_website_journal)

        mock_journal_history.create_or_update.assert_called_once_with(
            user, jc, "ADMITTED", 2019, 1, 1, None
        )

    @patch("migration.controller.JournalHistory")
    @patch("migration.controller.parse_yyyymmdd")
    def test_multiplos_eventos_chamam_create_or_update_na_ordem(
        self, mock_parse, mock_journal_history
    ):
        mock_parse.side_effect = [(2018, 1, 1), (2020, 6, 15)]
        user = MagicMock()
        jc = MagicMock()
        classic_website_journal = FakeClassicWebsiteJournal(
            status_history=[
                {"date": "20180101", "status": "C"},
                {"date": "20200615", "status": "S", "reason": "suspenso"},
            ]
        )

        migration_controller.create_journal_history(user, jc, classic_website_journal)

        self.assertEqual(mock_journal_history.create_or_update.call_count, 2)
        mock_journal_history.create_or_update.assert_has_calls(
            [
                call(user, jc, "ADMITTED", 2018, 1, 1, None),
                call(user, jc, "INTERRUPTED", 2020, 6, 15, "suspenso"),
            ]
        )


# ===========================================================================
# create_or_update_journal
# ===========================================================================
class CreateOrUpdateJournalTests(unittest.TestCase):
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    def _make_journal_proc(self, journal_data=None):
        journal_proc = MagicMock()
        journal_proc.start.return_value = MagicMock(name="journal_proc_event")
        journal_proc.migrated_data.data = journal_data or {}
        return journal_proc

    @patch("migration.controller.classic_ws")
    @patch("migration.controller.parse_yyyymmdd")
    @patch("migration.controller.OfficialJournal")
    @patch("migration.controller.Journal")
    @patch("migration.controller.Location")
    @patch("migration.controller.Language")
    @patch("migration.controller.Mission")
    @patch("migration.controller.Subject")
    @patch("migration.controller.Institution")
    @patch("migration.controller.Owner")
    @patch("migration.controller.Publisher")
    @patch("migration.controller.JournalCollection")
    @patch("migration.controller.create_journal_history")
    def test_caminho_feliz_retorna_journal_e_sincroniza_core(
        self,
        mock_create_history,
        mock_journal_collection,
        mock_publisher,
        mock_owner,
        mock_institution,
        mock_subject,
        mock_mission,
        mock_language,
        mock_location,
        mock_journal_cls,
        mock_official_journal,
        mock_parse,
        mock_classic_ws,
    ):
        user = MagicMock()
        journal_proc = self._make_journal_proc()
        mock_parse.return_value = (2020, 1, 1)

        fake_cw_journal = FakeClassicWebsiteJournal()
        mock_classic_ws.Journal.return_value = fake_cw_journal

        mock_official_journal.create_or_update.return_value = MagicMock()
        fake_journal = MagicMock()
        mock_journal_cls.create_or_update.return_value = fake_journal

        result = migration_controller.create_or_update_journal(
            user, journal_proc, force_update=False
        )

        self.assertIs(result, fake_journal)
        mock_official_journal.create_or_update.assert_called_once()
        mock_journal_cls.create_or_update.assert_called_once()
        mock_create_history.assert_called_once()
        journal_proc.update.assert_called_once()
        # core_synchronized deve ser marcado e o journal salvo ao final
        self.assertTrue(fake_journal.core_synchronized)
        fake_journal.save.assert_called()

    @patch("migration.controller.classic_ws")
    @patch("migration.controller.parse_yyyymmdd")
    @patch("migration.controller.OfficialJournal")
    def test_sem_eissn_e_pissn_levanta_valueerror_e_finaliza_evento(
        self, mock_official_journal, mock_parse, mock_classic_ws
    ):
        user = MagicMock()
        journal_proc = self._make_journal_proc()
        mock_parse.return_value = (2020, 1, 1)

        fake_cw_journal = FakeClassicWebsiteJournal(
            electronic_issn="", print_issn=""
        )
        mock_classic_ws.Journal.return_value = fake_cw_journal

        with self.assertRaises(ValueError):
            migration_controller.create_or_update_journal(
                user, journal_proc, force_update=False
            )

        event = journal_proc.start.return_value
        event.finish.assert_called_once()
        _, kwargs = event.finish.call_args
        self.assertFalse(kwargs["completed"])
        self.assertIsInstance(kwargs["exception"], ValueError)
        mock_official_journal.create_or_update.assert_not_called()

    @patch("migration.controller.classic_ws")
    @patch("migration.controller.parse_yyyymmdd")
    def test_erro_no_primeiro_bloco_propaga_excecao_original(
        self, mock_parse, mock_classic_ws
    ):
        user = MagicMock()
        journal_proc = self._make_journal_proc()
        mock_parse.side_effect = ValueError("data inválida")
        mock_classic_ws.Journal.return_value = FakeClassicWebsiteJournal()

        with self.assertRaises(ValueError):
            migration_controller.create_or_update_journal(
                user, journal_proc, force_update=False
            )

        event = journal_proc.start.return_value
        event.finish.assert_called_once()
        _, kwargs = event.finish.call_args
        self.assertFalse(kwargs["completed"])


# ===========================================================================
# create_or_update_issue
# ===========================================================================
class CreateOrUpdateIssueTests(unittest.TestCase):
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    @patch("migration.controller.classic_ws")
    @patch("migration.controller.Issue")
    @patch("migration.controller.TOC")
    @patch("migration.controller.Language")
    @patch("migration.controller.TocSection")
    def test_cria_issue_e_propaga_secoes_por_idioma(
        self, mock_toc_section, mock_language, mock_toc, mock_issue_cls, mock_classic_ws
    ):
        user = MagicMock()
        issue_proc = MagicMock()
        JournalProcCls = MagicMock()

        fake_classic_issue = MagicMock()
        fake_classic_issue.journal = "S0000-00002020000100001"
        fake_classic_issue.publication_year = "2020"
        fake_classic_issue.volume = "10"
        fake_classic_issue.number = "1"
        fake_classic_issue.supplement = None
        fake_classic_issue.total_documents = 5
        fake_classic_issue.order = "00012020000100001"
        fake_classic_issue.issue_label = "v10n1"
        fake_classic_issue.sections_by_code = {
            "AA": [{"language": "pt", "code": "AA", "text": "Editorial"}]
        }
        mock_classic_ws.Issue.return_value = fake_classic_issue

        journal_proc = MagicMock()
        journal_proc.journal = MagicMock()
        JournalProcCls.get.return_value = journal_proc

        # sem Issue ainda vinculado ao IssueProc: força o caminho de criação
        # (Issue.create_or_update), não o de reaproveitamento (issue.update).
        issue_proc.issue = None

        fake_issue = MagicMock()
        mock_issue_cls.create_or_update.return_value = fake_issue

        result = migration_controller.create_or_update_issue(
            user, issue_proc, force_update=True, JournalProc=JournalProcCls
        )

        self.assertIs(result, fake_issue)
        mock_issue_cls.create_or_update.assert_called_once()
        issue_proc.update.assert_called_once()
        mock_toc.create_or_update.assert_called_once_with(user, fake_issue, ordered=True)
        mock_toc_section.create_or_update.assert_called_once()

    @patch("migration.controller.classic_ws")
    @patch("migration.controller.Issue")
    @patch("migration.controller.TOC")
    @patch("migration.controller.Language")
    @patch("migration.controller.TocSection")
    def test_reaproveita_issue_ja_vinculado_ao_issue_proc(
        self, mock_toc_section, mock_language, mock_toc, mock_issue_cls, mock_classic_ws
    ):
        # issue_proc.issue já existe (remigração): reaproveita o Issue via
        # issue.update(**kwargs) em vez de Issue.create_or_update, evitando
        # duplicidade (#1024).
        user = MagicMock()
        issue_proc = MagicMock()
        JournalProcCls = MagicMock()

        fake_classic_issue = MagicMock()
        fake_classic_issue.journal = "S0000-00002020000100001"
        fake_classic_issue.publication_year = "2020"
        fake_classic_issue.volume = "10"
        fake_classic_issue.number = "1"
        fake_classic_issue.supplement = None
        fake_classic_issue.total_documents = 5
        fake_classic_issue.order = "00012020000100001"
        fake_classic_issue.issue_label = "v10n1"
        fake_classic_issue.sections_by_code = {}
        mock_classic_ws.Issue.return_value = fake_classic_issue

        journal_proc = MagicMock()
        journal_proc.journal = MagicMock()
        JournalProcCls.get.return_value = journal_proc

        existing_issue = MagicMock()
        issue_proc.issue = existing_issue

        result = migration_controller.create_or_update_issue(
            user, issue_proc, force_update=True, JournalProc=JournalProcCls
        )

        self.assertIs(result, existing_issue)
        existing_issue.update.assert_called_once()
        mock_issue_cls.create_or_update.assert_not_called()

    @patch("migration.controller.classic_ws")
    def test_journal_proc_inexistente_levanta_valueerror(self, mock_classic_ws):
        from importlib import import_module

        controller = import_module(MODULE)

        user = MagicMock()
        issue_proc = MagicMock()

        class DoesNotExist(Exception):
            pass

        JournalProcCls = MagicMock()
        JournalProcCls.DoesNotExist = DoesNotExist
        JournalProcCls.get.side_effect = DoesNotExist()

        fake_classic_issue = MagicMock()
        fake_classic_issue.journal = "PID-INEXISTENTE"
        mock_classic_ws.Issue.return_value = fake_classic_issue

        with self.assertRaises(ValueError):
            controller.create_or_update_issue(
                user, issue_proc, force_update=False, JournalProc=JournalProcCls
            )

    @patch("migration.controller.classic_ws")
    def test_journal_proc_sem_journal_associado_levanta_valueerror(
        self, mock_classic_ws
    ):
        user = MagicMock()
        issue_proc = MagicMock()
        JournalProcCls = MagicMock()

        journal_proc = MagicMock()
        journal_proc.journal = None
        JournalProcCls.get.return_value = journal_proc

        mock_classic_ws.Issue.return_value = MagicMock()

        with self.assertRaises(ValueError):
            migration_controller.create_or_update_issue(
                user, issue_proc, force_update=False, JournalProc=JournalProcCls
            )


# ===========================================================================
# create_or_update_article
# ===========================================================================
class CreateOrUpdateArticleTests(unittest.TestCase):
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    @patch("migration.controller.Article")
    @patch("migration.controller.tracker_choices")
    def test_cria_artigo_e_marca_status_como_done(self, mock_choices, mock_article):
        mock_choices.PROGRESS_STATUS_DONE = "done"
        user = MagicMock()
        article_proc = MagicMock()
        fake_article = MagicMock()
        mock_article.create_or_update.return_value = fake_article

        result = migration_controller.create_or_update_article(
            user, article_proc, force_update=False
        )

        self.assertIs(result, fake_article)
        mock_article.create_or_update.assert_called_once_with(
            user,
            article_proc.sps_pkg,
            issue=article_proc.issue_proc.issue,
            journal=article_proc.issue_proc.journal_proc.journal,
            collection=article_proc.collection,
        )
        self.assertEqual(article_proc.migrated_data.migration_status, "done")
        self.assertEqual(article_proc.migration_status, "done")
        self.assertEqual(article_proc.updated_by, user)
        article_proc.save.assert_called_once()


# ===========================================================================
# get_classic_website
# ===========================================================================
class GetClassicWebsiteTests(unittest.TestCase):
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    @patch("migration.controller.classic_ws")
    @patch("migration.controller.ClassicWebsiteConfiguration")
    def test_retorna_classic_website_configurado(
        self, mock_config_cls, mock_classic_ws
    ):
        config = MagicMock()
        config.bases_work_path = "/dados/bases/bases-work"
        config.bases_translation_path = "/dados/bases/translation"
        config.bases_pdf_path = "/dados/bases/pdf"
        config.bases_xml_path = "/dados/bases/xml"
        config.htdocs_img_revistas_path = "/dados/htdocs/img/revistas"
        config.serial_path = "/dados/serial"
        config.title_path = "/dados/title"
        config.issue_path = "/dados/issue"
        config.alternative_htdocs_img_revistas_path = None
        mock_config_cls.objects.get.return_value = config

        fake_cw = MagicMock()
        mock_classic_ws.ClassicWebsite.return_value = fake_cw

        result = migration_controller.get_classic_website("scl")

        self.assertIs(result, fake_cw)
        mock_config_cls.objects.get.assert_called_once_with(collection__acron="scl")
        mock_classic_ws.ClassicWebsite.assert_called_once()

    @patch("migration.controller.UnexpectedEvent")
    @patch("migration.controller.ClassicWebsiteConfiguration")
    def test_erro_registra_unexpectedevent_e_retorna_none(
        self, mock_config_cls, mock_unexpected_event
    ):
        mock_config_cls.objects.get.side_effect = Exception("config ausente")

        result = migration_controller.get_classic_website("scl")

        self.assertIsNone(result)
        mock_unexpected_event.create.assert_called_once()
        _, kwargs = mock_unexpected_event.create.call_args
        self.assertEqual(kwargs["detail"]["collection_acron"], "scl")


# ===========================================================================
# migrate_issue_files
# ===========================================================================
class MigrateIssueFilesTests(unittest.TestCase):
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    @patch("migration.controller.MigratedFile")
    @patch("migration.controller.get_classic_website")
    def test_arquivos_migrados_com_sucesso(self, mock_get_cw, mock_migrated_file):
        user = MagicMock()
        collection = MagicMock()
        collection.acron = "scl"

        classic_website = MagicMock()
        classic_website.get_issue_folder_content.return_value = [
            {
                "path": "/x/en_artigo.pdf",
                "relative_path": "en_artigo.pdf",
                "name": "en_artigo.pdf",
                "type": "pdf",
                "lang": "en",
                "key": None,
                "part": "before",
                "content": None,
                "modified_date": "2020-01-01",
            },
            None,  # deve ser ignorado
            {"path": "/x/erro.xml", "error": "arquivo corrompido"},
        ]
        mock_get_cw.return_value = classic_website

        instance = MagicMock()
        instance.id = 42
        mock_migrated_file.create_or_update.return_value = instance

        result = migration_controller.migrate_issue_files(
            user, collection, "revista", "v10n1", force_update=True
        )

        self.assertEqual(result["migrated"], [42])
        self.assertEqual(len(result["exceptions"]), 1)
        self.assertEqual(result["exceptions"][0]["error"], "arquivo corrompido")
        mock_migrated_file.create_or_update.assert_called_once()
        _, kwargs = mock_migrated_file.create_or_update.call_args
        self.assertEqual(kwargs["part"], "1")  # PARTS["before"] == "1"

    @patch("migration.controller.get_classic_website")
    def test_classic_website_ausente_gera_excecao_controlada(self, mock_get_cw):
        mock_get_cw.return_value = None
        user = MagicMock()
        collection = MagicMock()
        collection.acron = "scl"

        result = migration_controller.migrate_issue_files(
            user, collection, "revista", "v10n1", force_update=False
        )

        self.assertEqual(result["migrated"], [])
        self.assertEqual(len(result["exceptions"]), 1)
        self.assertIn("Classic website not found", result["exceptions"][0]["error"])

    @patch("migration.controller.MigratedFile")
    @patch("migration.controller.get_classic_website")
    def test_erro_ao_criar_migratedfile_nao_interrompe_o_loop(
        self, mock_get_cw, mock_migrated_file
    ):
        user = MagicMock()
        collection = MagicMock()
        collection.acron = "scl"

        classic_website = MagicMock()
        classic_website.get_issue_folder_content.return_value = [
            {"path": "/x/a.xml", "relative_path": "a.xml", "name": "a.xml", "type": "xml"},
            {"path": "/x/b.xml", "relative_path": "b.xml", "name": "b.xml", "type": "xml"},
        ]
        mock_get_cw.return_value = classic_website

        ok_instance = MagicMock()
        ok_instance.id = 7
        mock_migrated_file.create_or_update.side_effect = [
            Exception("falha ao salvar"),
            ok_instance,
        ]

        result = migration_controller.migrate_issue_files(
            user, collection, "revista", "v10n1", force_update=False
        )

        self.assertEqual(result["migrated"], [7])
        self.assertEqual(len(result["exceptions"]), 1)
        self.assertEqual(result["exceptions"][0]["error"], "falha ao salvar")

    @patch("migration.controller.MigratedFile")
    @patch("migration.controller.get_classic_website")
    def test_arquivo_duplicado_como_asset_mantem_tipo_original(
        self, mock_get_cw, mock_migrated_file
    ):
        user = MagicMock()
        collection = MagicMock()
        collection.acron = "scl"

        classic_website = MagicMock()
        classic_website.get_issue_folder_content.return_value = [
            {
                "path": "/x/bases/xml/revista/v10n1/a.xml",
                "relative_path": "bases/xml/revista/v10n1/a.xml",
                "name": "a.xml",
                "type": "xml",
            },
            {
                "path": "/x/bases/xml/revista/v10n1/a.xml",
                "relative_path": "bases/xml/revista/v10n1/a.xml",
                "name": "a.xml",
                "type": "asset",
            },
        ]
        mock_get_cw.return_value = classic_website

        instance = MagicMock()
        instance.id = 1
        mock_migrated_file.create_or_update.return_value = instance

        result = migration_controller.migrate_issue_files(
            user, collection, "revista", "v10n1", force_update=True
        )

        self.assertEqual(result["migrated"], [1])
        mock_migrated_file.create_or_update.assert_called_once()
        _, kwargs = mock_migrated_file.create_or_update.call_args
        self.assertEqual(kwargs["component_type"], "xml")


# ===========================================================================
# PkgZipBuilder
# ===========================================================================
class PkgZipBuilderTests(unittest.TestCase):
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    def _make_xml_with_pre(self):
        xml_with_pre = MagicMock()
        xml_with_pre.sps_pkg_name = "1234-5678-2020-1-1-1"
        xml_with_pre.xmltree = MagicMock()
        xml_with_pre.tostring.return_value = b"<article/>"
        return xml_with_pre

    def test_init_define_atributos_basicos(self):
        xml_with_pre = self._make_xml_with_pre()
        builder = migration_controller.PkgZipBuilder(xml_with_pre)

        self.assertIs(builder.xml_with_pre, xml_with_pre)
        self.assertEqual(builder.sps_pkg_name, "1234-5678-2020-1-1-1")
        self.assertEqual(builder.components, {})
        self.assertEqual(builder.texts, {})
        self.assertEqual(builder.replacements, {})

    @patch("migration.controller.ArticleAssets")
    def test_build_sps_package_add_assets_registra_componente_e_substituicao(
        self, mock_article_assets
    ):
        xml_with_pre = self._make_xml_with_pre()
        builder = migration_controller.PkgZipBuilder(xml_with_pre)

        graphic = MagicMock()
        graphic.xlink_href = "original/imagem.tif"
        graphic.is_supplementary_material = False
        graphic.id = "fig1"
        graphic.name_canonical.return_value = "1234-5678-2020-1-1-1-fig1"

        mock_assets_instance = MagicMock()
        mock_assets_instance.items = [graphic]
        mock_article_assets.return_value = mock_assets_instance

        asset = MagicMock()
        asset.file.path = "/media/imagem.tif"
        asset.original_href = "original/imagem.tif"

        issue_proc = MagicMock()
        queryset = MagicMock()
        queryset.exists.return_value = True
        queryset.__iter__.return_value = iter([asset])
        issue_proc.find_asset.return_value = queryset

        zf = MagicMock()

        builder._build_sps_package_add_assets(zf, issue_proc)

        self.assertIn("original/imagem.tif", builder.replacements)
        sps_filename = builder.replacements["original/imagem.tif"]
        self.assertIn(sps_filename, builder.components)
        self.assertEqual(
            builder.components[sps_filename]["component_type"], "asset"
        )
        mock_assets_instance.replace_names.assert_called_once_with(
            builder.replacements
        )
        zf.write.assert_called_once()

    @patch("migration.controller.ArticleAssets")
    def test_build_sps_package_add_assets_registra_nao_encontrado(
        self, mock_article_assets
    ):
        xml_with_pre = self._make_xml_with_pre()
        builder = migration_controller.PkgZipBuilder(xml_with_pre)

        graphic = MagicMock()
        graphic.xlink_href = "original/faltante.tif"
        mock_assets_instance = MagicMock()
        mock_assets_instance.items = [graphic]
        mock_article_assets.return_value = mock_assets_instance

        issue_proc = MagicMock()
        queryset = MagicMock()
        queryset.exists.return_value = False
        issue_proc.find_asset.return_value = queryset

        zf = MagicMock()

        builder._build_sps_package_add_assets(zf, issue_proc)

        self.assertEqual(
            builder.components["original/faltante.tif"], {"failures": "Not found"}
        )
        zf.write.assert_not_called()

    def test_build_sps_package_add_xml_escreve_conteudo_no_zip(self):
        xml_with_pre = self._make_xml_with_pre()
        builder = migration_controller.PkgZipBuilder(xml_with_pre)
        zf = MagicMock()

        builder._build_sps_package_add_xml(zf)

        zf.writestr.assert_called_once_with(
            "1234-5678-2020-1-1-1.xml", b"<article/>"
        )
        self.assertEqual(
            builder.components["1234-5678-2020-1-1-1.xml"],
            {"component_type": "xml"},
        )


# ===========================================================================
# get_migrated_xml_with_pre
# ===========================================================================
class GetMigratedXmlWithPreTests(unittest.TestCase):
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    @patch("migration.controller.XMLWithPre")
    @patch("migration.controller.HTMLXML")
    def test_usa_htmlxml_quando_existe_e_corrige_pid_v2_e_order(
        self, mock_htmlxml, mock_xml_with_pre
    ):
        article_proc = MagicMock()
        article_proc.pid = "S0000-000020200001000015"

        obj = MagicMock()
        obj.file.path = "/media/artigo.xml"
        mock_htmlxml.get.return_value = obj

        item = MagicMock()
        item.v2 = "pid-antigo"
        item.order = None
        mock_xml_with_pre.create.return_value = [item]

        result = migration_controller.get_migrated_xml_with_pre(article_proc)

        self.assertIs(result, item)
        self.assertEqual(item.v2, article_proc.pid)
        self.assertEqual(item.order, article_proc.pid[-5:])

    @patch("migration.controller.XMLWithPre")
    @patch("migration.controller.HTMLXML")
    def test_usa_migrated_xml_quando_htmlxml_nao_existe(
        self, mock_htmlxml, mock_xml_with_pre
    ):
        class DoesNotExist(Exception):
            pass

        mock_htmlxml.DoesNotExist = DoesNotExist
        mock_htmlxml.get.side_effect = DoesNotExist()

        article_proc = MagicMock()
        article_proc.pid = "S0000-000020200001000015"
        article_proc.migrated_xml.file.path = "/media/migrado.xml"

        item = MagicMock()
        item.v2 = article_proc.pid  # já correto, não deve ser sobrescrito
        item.order = "00001"
        mock_xml_with_pre.create.return_value = [item]

        result = migration_controller.get_migrated_xml_with_pre(article_proc)

        self.assertIs(result, item)

    @patch("migration.controller.XMLWithPre")
    @patch("migration.controller.HTMLXML")
    def test_erro_ao_processar_xml_levanta_xmlversionxmlwithpreerror(
        self, mock_htmlxml, mock_xml_with_pre
    ):
        class DoesNotExist(Exception):
            pass

        mock_htmlxml.DoesNotExist = DoesNotExist
        mock_htmlxml.get.side_effect = DoesNotExist()

        article_proc = MagicMock()
        article_proc.pid = "S0000-000020200001000015"
        article_proc.migrated_xml.file.path = "/media/migrado.xml"

        mock_xml_with_pre.create.side_effect = Exception("xml malformado")

        with self.assertRaises(migration_controller.XMLVersionXmlWithPreError):
            migration_controller.get_migrated_xml_with_pre(article_proc)


# ===========================================================================
# get_bases_work_acron_id_file_records
# ===========================================================================
class GetBasesWorkAcronIdFileRecordsTests(unittest.TestCase):
    """
    Usa arquivos .id reais (diretório temporário) lidos por ClassicIdFile;
    os caminhos de erro simulam ClassicIdFile.
    """

    ACRON_ID = """!ID 0000001
!v706!i
!v035!0044-5967
!v036!20193
!v091!20191001
!ID 0000002
!v706!o
!v880!S0044-59672019000300001
!v091!20191005
!ID 0000003
!v706!h
!v880!S0044-59672019000300001
!ID 0000004
!v706!o
!v880!S0044-59672019000300002
!v091!20191005
!ID 0000005
!v706!h
!v880!S0044-59672019000300002
!ID 0000006
!v706!p
!v880!S0044-59672019000300002
!v704!paragrafo interno
!ID 0000007
!v706!o
!v880!S0044-59672019000300003
!v091!20191005
!ID 0000008
!v706!h
!v880!S0044-59672019000300003
"""
    P_FILE = """!ID 0000001
!v706!p
!v880!S0044-59672019000300001
!v704!paragrafo externo
"""

    def setUp(self):
        import os
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.bases_work = os.path.join(self.tmp.name, "bases-work")
        self.bases = os.path.join(self.tmp.name, "bases")
        self.source_path = os.path.join(self.bases_work, "acron", "acron.id")
        os.makedirs(os.path.dirname(self.source_path))
        with open(self.source_path, "w", encoding="iso-8859-1") as fp:
            fp.write(self.ACRON_ID)

        # p externo só para o documento 00001 (sem p no acron.id)
        p_dir = os.path.join(self.bases, "artigo", "p", "0044-5967", "2019", "0003")
        os.makedirs(p_dir)
        with open(os.path.join(p_dir, "00001.id"), "w", encoding="iso-8859-1") as fp:
            fp.write(self.P_FILE)

        self.classic_website = MagicMock()
        self.classic_website.classic_website_paths.bases_work_path = self.bases_work
        self.classic_website.classic_website_paths.bases_path = self.bases

    def tearDown(self):
        self.tmp.cleanup()

    def _items(self, source_path=None):
        return list(
            migration_controller.get_bases_work_acron_id_file_records(
                source_path or self.source_path, self.classic_website
            )
        )

    def test_gera_registros_de_artigo_e_issue(self):
        items = self._items()

        self.assertEqual(
            [(i["item_type"], i["item_pid"]) for i in items],
            [
                ("issue", "0044-596720190003"),
                ("article", "S0044-59672019000300001"),
                ("article", "S0044-59672019000300002"),
                ("article", "S0044-59672019000300003"),
            ],
        )
        issue, art1, art2, art3 = items
        self.assertEqual(issue["data"]["v036"], [{"_": "20193"}])
        # p no acron.id: fica nos registros do artigo
        self.assertEqual(
            [r["v706"][0]["_"] for r in art2["data"]], ["o", "h", "p"]
        )
        self.assertEqual(
            art2["data"][2]["v704"], [{"_": "paragrafo interno"}]
        )
        # sem p no acron.id e sem arquivo p externo: só os registros do acron.id
        self.assertEqual([r["v706"][0]["_"] for r in art3["data"]], ["o", "h"])

    def test_paragrafos_externos_sao_incluidos_nos_registros_do_artigo(self):
        # sem p no acron.id: os de bases/artigo/p/.../00001.id entram nos
        # registros do próprio artigo; não há item "paragraph" separado
        items = self._items()

        self.assertNotIn("paragraph", [i["item_type"] for i in items])
        art1 = [i for i in items if i["item_pid"] == "S0044-59672019000300001"]
        self.assertEqual([i["item_type"] for i in art1], ["article"])
        self.assertEqual(
            [r["v706"][0]["_"] for r in art1[0]["data"]], ["o", "h", "p"]
        )
        self.assertEqual(
            art1[0]["data"][2]["v704"], [{"_": "paragrafo externo"}]
        )

    def test_paragrafos_externos_em_bases_work_tem_prioridade(self):
        import os

        p_dir = os.path.join(
            self.bases_work, "artigo", "p", "0044-5967", "2019", "0003"
        )
        os.makedirs(p_dir)
        with open(
            os.path.join(p_dir, "00001.id"), "w", encoding="iso-8859-1"
        ) as fp:
            fp.write(self.P_FILE.replace("externo", "bases-work"))

        items = self._items()

        art1 = [i for i in items if i["item_pid"] == "S0044-59672019000300001"]
        self.assertEqual(
            art1[0]["data"][2]["v704"], [{"_": "paragrafo bases-work"}]
        )

    def test_usa_bases_work_e_bases_para_registros_p(self):
        with patch(f"{MODULE}.ClassicIdFile") as MockIdFile:
            MockIdFile.return_value.items.return_value = []
            MockIdFile.return_value.broken_batches.return_value = []

            self.assertEqual([], self._items())

        MockIdFile.assert_called_once_with(
            "artigo",
            self.source_path,
            p_records_base_paths=[self.bases_work, self.bases],
        )

    def _items_with_fake_id_file(self, items=(), broken_batches=()):
        with patch(f"{MODULE}.ClassicIdFile") as MockIdFile:
            MockIdFile.return_value.items.return_value = list(items)
            MockIdFile.return_value.broken_batches.return_value = list(
                broken_batches
            )
            return self._items()

    def test_erro_em_item_gera_exception_e_continua(self):
        bad = MagicMock(kind="document", pid="S0044-59672019000300001")
        type(bad).records = mock.PropertyMock(
            side_effect=ValueError("registro invalido")
        )
        good = MagicMock(
            kind="document",
            pid="S0044-59672019000300002",
            records=[{"v706": [{"_": "o"}]}],
        )

        items = self._items_with_fake_id_file(items=[bad, good])

        self.assertEqual(
            [
                {
                    "item_type": "exception",
                    "item_pid": "S0044-59672019000300001",
                    "exception": "registro invalido",
                },
                {
                    "item_type": "article",
                    "item_pid": "S0044-59672019000300002",
                    "data": [{"v706": [{"_": "o"}]}],
                },
            ],
            items,
        )

    def test_erro_em_lote_quebrado_gera_exception_e_continua(self):
        bad = MagicMock(pid="S0044-59672019000300009", record_types=("o",))
        type(bad).main_records = mock.PropertyMock(
            side_effect=ValueError("lote invalido")
        )
        good = MagicMock(
            pid=None,
            mfn=7,
            last_mfn=8,
            offset=120,
            record_types=("h", None),
            main_records=[{"v706": [{"_": "h"}]}, {}],
        )

        items = self._items_with_fake_id_file(broken_batches=[bad, good])

        self.assertEqual(
            [
                {
                    "item_type": "exception",
                    "item_pid": "S0044-59672019000300009",
                    "exception": "lote invalido",
                },
                {
                    # sem PID: identificado pelo MFN; tipo ausente vira ""
                    "item_type": "broken",
                    "item_pid": "MFN7",
                    "data": {
                        "record_types": "h",
                        "mfn": 7,
                        "last_mfn": 8,
                        "offset": 120,
                        "records": [{"v706": [{"_": "h"}]}, {}],
                    },
                },
            ],
            items,
        )

    def test_item_de_outro_tipo_e_ignorado(self):
        other = MagicMock(kind="journal", pid="0044-5967")

        self.assertEqual([], self._items_with_fake_id_file(items=[other]))

    def _write(self, name, content):
        import os

        source_path = os.path.join(self.bases_work, "acron", name)
        with open(source_path, "w", encoding="iso-8859-1") as fp:
            fp.write(content)
        return source_path

    def test_lotes_quebrados_sao_armazenados_como_broken(self):
        source_path = self._write(
            "quebrado.id",
            "!ID 0000001\n!v706!o\n!v880!S0044-59672019000300009\n!v091!20191005\n"
            "!ID 0000002\n!v706!o\n!v880!S0044-59672019000300010\n!v091!20191005\n"
            "!ID 0000003\n!v706!h\n!v880!S0044-59672019000300010\n"
            "!ID 0000004\n!v706!h\n!v880!S0044-59672019000300011\n"
            "!ID 0000005\n!v706!f\n!v880!S0044-59672019000300011\n",
        )

        items = self._items(source_path)

        self.assertEqual(
            [
                # itens bons primeiro; lotes quebrados depois, separados
                ("article", "S0044-59672019000300010"),
                ("broken", "S0044-59672019000300009"),
                ("broken", "S0044-59672019000300011"),
            ],
            [(i.get("item_type"), i["item_pid"]) for i in items],
        )
        self.assertNotIn("exception", items[1])
        self.assertEqual("o", items[1]["data"]["record_types"])
        self.assertEqual(1, items[1]["data"]["mfn"])
        self.assertEqual("hf", items[2]["data"]["record_types"])
        self.assertEqual((4, 5), (items[2]["data"]["mfn"], items[2]["data"]["last_mfn"]))
        self.assertEqual(
            ["h", "f"], [r["v706"][0]["_"] for r in items[2]["data"]["records"]]
        )

    def test_o_solto_e_documento_completo_mais_adiante(self):
        source_path = self._write(
            "substituido.id",
            "!ID 0000001\n!v706!o\n!v880!S0044-59672019000300009\n!v091!20191005\n"
            "!ID 0000002\n!v706!o\n!v880!S0044-59672019000300009\n!v091!20191010\n"
            "!ID 0000003\n!v706!h\n!v880!S0044-59672019000300009\n",
        )

        items = self._items(source_path)

        # o lote quebrado e o documento têm item_type diferentes: não se sobrescrevem
        self.assertEqual(
            [
                ("article", "S0044-59672019000300009"),
                ("broken", "S0044-59672019000300009"),
            ],
            [(i.get("item_type"), i["item_pid"]) for i in items],
        )
        self.assertEqual(["o", "h"], [r["v706"][0]["_"] for r in items[0]["data"]])

    def test_arquivo_inexistente_lanca_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self._items("/caminho/inexistente/acron.id")


# ===========================================================================
# import_journal_acron_id_records
# ===========================================================================
class ImportJournalAcronIdRecordsTests(unittest.TestCase):
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    def _make_journal_proc(self):
        journal_proc = MagicMock()
        journal_proc.acron = "rt"
        journal_proc.collection.acron = "scl"
        return journal_proc

    def _import(
        self,
        has_changes,
        records=None,
        force_update=False,
        pending_issue_pids=("0000-000020000001",),
    ):
        """
        Executa import_journal_acron_id_records com dependências simuladas.

        ``records``: lista de itens de get_bases_work_acron_id_file_records
        ou exceção levantada durante a leitura do arquivo.
        """
        journal_proc = self._make_journal_proc()
        issueproc_qs = MagicMock()
        issueproc_qs.values_list.return_value = [11]
        journal_proc.issueproc_set.filter.return_value = issueproc_qs

        classic_website = MagicMock()
        classic_website.classic_website_paths.bases_work_path = "/bases-work"

        journal_id_file = MagicMock()
        journal_id_file.data = {
            "stats": {"total_id_file_records": 1},
            "pending_issue_pids": list(pending_issue_pids),
        }

        def get_records(source_path, cw, last_run_date=None):
            for item in records or []:
                if isinstance(item, Exception):
                    raise item
                yield item

        user = MagicMock()
        journal_id_file.has_changes.return_value = has_changes

        with patch(
            "migration.controller.get_classic_website", return_value=classic_website
        ), patch("migration.controller.JournalAcronIdFile") as mock_acron_id_file, patch(
            "migration.controller.get_bases_work_acron_id_file_records",
            side_effect=get_records,
        ) as mock_get_records, patch(
            "migration.controller.IdFileRecord"
        ) as mock_id_file_record, patch(
            "migration.controller.MigratedArticle"
        ) as mock_migrated_article, translation.override(
            "en"
        ):
            mock_migrated_article.objects.filter.return_value.aggregate.return_value = {
                "d": "20191005"
            }
            mock_acron_id_file.create_or_update.return_value = journal_id_file
            detail = migration_controller.import_journal_acron_id_records(
                user, journal_proc, force_update=force_update
            )
        return {
            "detail": detail,
            "user": user,
            "journal_proc": journal_proc,
            "journal_id_file": journal_id_file,
            "acron_id_file": mock_acron_id_file,
            "get_records": mock_get_records,
            "id_file_record": mock_id_file_record,
            "migrated_article": mock_migrated_article,
        }

    def test_arquivo_alterado_le_registros_e_marca_como_lido(self):
        r = self._import(
            has_changes=True,
            records=[
                {"item_type": "article", "item_pid": "S0000-0000202000010001", "data": {}},
            ],
        )

        detail = r["detail"]
        self.assertEqual(detail["exceptions"], [])
        self.assertNotIn("traceback", detail)
        r["id_file_record"].create_or_update.assert_called_once()
        r["acron_id_file"].create_or_update.assert_called_once_with(
            user=r["user"],
            collection=r["journal_proc"].collection,
            journal_acron="rt",
            source_path="/bases-work/rt/rt.id",
        )
        r["journal_id_file"].mark_as_read.assert_called_once_with(r["user"])
        r["journal_proc"].issueproc_set.filter.assert_called_once_with(
            pid__in=["0000-000020000001"]
        )
        self.assertEqual(detail["issue_proc_id_list"], [11])
        self.assertEqual(detail["stats"], r["journal_id_file"].data["stats"])

    def test_force_update_e_repassado_a_has_changes(self):
        r = self._import(has_changes=True, force_update=True)

        r["journal_id_file"].has_changes.assert_called_once_with(force_update=True)

    def test_sem_force_update_le_somente_a_partir_da_data_mais_recente(self):
        r = self._import(has_changes=True)

        r["migrated_article"].objects.filter.assert_called_once_with(
            collection=r["journal_proc"].collection,
            pid__startswith=f"S{r['journal_proc'].pid}",
        )
        _, kwargs = r["get_records"].call_args
        self.assertEqual(kwargs["last_run_date"], "20191005")

    def test_force_update_le_o_arquivo_inteiro(self):
        r = self._import(has_changes=True, force_update=True)

        r["migrated_article"].objects.filter.assert_not_called()
        _, kwargs = r["get_records"].call_args
        self.assertIsNone(kwargs["last_run_date"])

    def test_arquivo_ja_lido_completamente_nao_e_relido(self):
        r = self._import(has_changes=False)

        detail = r["detail"]
        self.assertIn("up-to-date", detail["message"])
        r["get_records"].assert_not_called()
        r["journal_id_file"].mark_as_read.assert_not_called()
        # os fascículos pendentes continuam sendo informados
        self.assertEqual(detail["issue_proc_id_list"], [11])

    def test_leitura_incompleta_nao_marca_como_lido(self):
        r = self._import(
            has_changes=True,
            records=[
                {"item_type": "article", "item_pid": "S0000-0000202000010001", "data": {}},
                OSError("interrompido"),
            ],
        )

        detail = r["detail"]
        self.assertIn("traceback", detail)
        self.assertIn("Incomplete reading", detail["message"])
        # será lido novamente na próxima execução
        r["journal_id_file"].mark_as_read.assert_not_called()
        # os registros já carregados ficam disponíveis para processar
        r["id_file_record"].create_or_update.assert_called_once()
        self.assertEqual(detail["issue_proc_id_list"], [11])

    def test_falha_em_registro_individual_nao_impede_marcacao(self):
        r = self._import(
            has_changes=True,
            records=[
                {"item_pid": "S0000-0000202000010001", "exception": "erro"},
                {"item_type": "article", "item_pid": "S0000-0000202000010002", "data": {}},
            ],
        )

        detail = r["detail"]
        self.assertEqual(detail["exceptions"], ["erro"])
        r["id_file_record"].create_or_update.assert_called_once()
        r["journal_id_file"].mark_as_read.assert_called_once()

    def test_arquivo_inexistente(self):
        journal_proc = self._make_journal_proc()
        classic_website = MagicMock()
        classic_website.classic_website_paths.bases_work_path = "/bases-work"

        with patch(
            "migration.controller.get_classic_website", return_value=classic_website
        ), patch("migration.controller.JournalAcronIdFile") as mock_acron_id_file:
            mock_acron_id_file.create_or_update.side_effect = FileNotFoundError()
            detail = migration_controller.import_journal_acron_id_records(
                MagicMock(), journal_proc, force_update=False
            )

        self.assertEqual(detail["message"], "File not found: /bases-work/rt/rt.id")

    @patch("migration.controller.JournalAcronIdFile")
    @patch("migration.controller.get_classic_website")
    def test_erro_generico_registra_traceback_no_detail(
        self, mock_get_cw, mock_journal_acron_id_file
    ):
        user = MagicMock()
        journal_proc = self._make_journal_proc()

        mock_get_cw.return_value = MagicMock()
        mock_journal_acron_id_file.create_or_update.side_effect = Exception("boom")

        detail = migration_controller.import_journal_acron_id_records(
            user, journal_proc, force_update=True
        )

        self.assertIn("traceback", detail)
        self.assertIn("exceptions", detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
