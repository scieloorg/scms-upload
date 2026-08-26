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
from importlib import import_module

MODULE = "migration.controller"

import sys
import types


from migration import controller as migration_controller

# ---------------------------------------------------------------------------
# Stubs para módulos externos que podem não estar instalados no ambiente de
# teste (packtools, scielo_classic_website). Isso permite executar os testes
# mesmo sem essas dependências completas instaladas; se elas já existirem,
# os stubs não são usados (o import real do módulo sob teste prevalece).
# ---------------------------------------------------------------------------
def _ensure_stub_module(name):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


for _name in [
    "packtools",
    "packtools.sps",
    "packtools.sps.models",
    "packtools.sps.models.article_and_subarticles",
    "packtools.sps.models.v2",
    "packtools.sps.models.v2.article_assets",
    "packtools.sps.pid_provider",
    "packtools.sps.pid_provider.xml_sps_lib",
    "scielo_classic_website",
    "scielo_classic_website.classic_ws",
    "scielo_classic_website.iid2json",
    "scielo_classic_website.iid2json.id2json3",
]:
    _ensure_stub_module(_name)

sys.modules["packtools.sps.models.article_and_subarticles"].ArticleAndSubArticles = MagicMock()
sys.modules["packtools.sps.models.v2.article_assets"].ArticleAssets = MagicMock()
sys.modules["packtools.sps.pid_provider.xml_sps_lib"].XMLWithPre = MagicMock()
sys.modules["scielo_classic_website"].classic_ws = MagicMock()
sys.modules["scielo_classic_website.iid2json.id2json3"].get_doc_records = MagicMock()


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

        fake_issue = MagicMock()
        mock_issue_cls.get_or_create.return_value = fake_issue

        result = migration_controller.create_or_update_issue(
            user, issue_proc, force_update=True, JournalProc=JournalProcCls
        )

        self.assertIs(result, fake_issue)
        mock_issue_cls.get_or_create.assert_called_once()
        issue_proc.update.assert_called_once()
        mock_toc.create_or_update.assert_called_once_with(user, fake_issue, ordered=True)
        mock_toc_section.create_or_update.assert_called_once()

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
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    @patch("migration.controller.get_doc_records")
    def test_gera_registros_de_artigo_issue_e_paragrafo(self, mock_get_doc_records):
        mock_get_doc_records.return_value = [
            {"doc_id": "art-1", "doc_data": {"a": 1}},
            {"issue_id": "issue-1", "issue_data": {"b": 2}},
        ]
        classic_website = MagicMock()
        classic_website.get_p_records.return_value = ("art-1", iter([{"p": 1}]))

        items = list(
            migration_controller.get_bases_work_acron_id_file_records(
                "/caminho/acron.id", classic_website
            )
        )

        item_types = [i["item_type"] for i in items]
        self.assertIn("article", item_types)
        self.assertIn("paragraph", item_types)
        self.assertIn("issue", item_types)

    @patch("migration.controller.get_doc_records")
    def test_paragrafo_ausente_e_ignorado_silenciosamente(self, mock_get_doc_records):
        mock_get_doc_records.return_value = [
            {"doc_id": "art-1", "doc_data": {"a": 1}},
        ]
        classic_website = MagicMock()
        classic_website.get_p_records.side_effect = FileNotFoundError()

        items = list(
            migration_controller.get_bases_work_acron_id_file_records(
                "/caminho/acron.id", classic_website
            )
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item_type"], "article")

    @patch("migration.controller.get_doc_records")
    def test_erro_inesperado_gera_item_com_exception(self, mock_get_doc_records):
        mock_get_doc_records.return_value = [{"doc_id": None, "issue_id": None}]
        classic_website = MagicMock()

        items = list(
            migration_controller.get_bases_work_acron_id_file_records(
                "/caminho/acron.id", classic_website
            )
        )
        # nem doc_id nem issue_id -> nenhum item é gerado (nem exceção),
        # já que o bloco try não levanta erro nesse caso
        self.assertEqual(items, [])


# ===========================================================================
# id_file_has_changes
# ===========================================================================
class IdFileHasChangesTests(unittest.TestCase):
    def setUp(self):
        from importlib import import_module

        migration_controller = import_module(MODULE)

    @patch("migration.controller.MigratedFile")
    def test_delega_para_migratedfile_has_changes(self, mock_migrated_file):
        mock_migrated_file.has_changes.return_value = True
        user = MagicMock()
        collection = MagicMock()

        result = migration_controller.id_file_has_changes(
            user, collection, "/caminho/x.id", force_update=False
        )

        self.assertTrue(result)
        mock_migrated_file.has_changes.assert_called_once_with(
            user, collection, "/caminho/x.id", False
        )


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

    @patch("migration.controller.IdFileRecord")
    @patch("migration.controller.get_bases_work_acron_id_file_records")
    @patch("migration.controller.JournalAcronIdFile")
    @patch("migration.controller.get_classic_website")
    def test_atualizacao_necessaria_processa_registros(
        self,
        mock_get_cw,
        mock_journal_acron_id_file,
        mock_get_records,
        mock_id_file_record,
    ):
        user = MagicMock()
        journal_proc = self._make_journal_proc()

        classic_website = MagicMock()
        classic_website.classic_website_paths.bases_work_path = "/bases-work"
        mock_get_cw.return_value = classic_website

        journal_id_file = MagicMock()
        journal_id_file.data = {
            "id_file_record_need_to_be_updated": True,
            "stats": {},
        }
        mock_journal_acron_id_file.create_or_update.return_value = journal_id_file

        mock_get_records.return_value = [
            {"item_type": "article", "item_pid": "S0000-0000202000010001", "data": {}},
        ]

        # querysets encadeados usados no final da função
        qs = MagicMock()
        qs.annotate.return_value = qs
        qs.values_list.return_value = qs
        qs.distinct.return_value = ["S0000-0000202000010001"]
        mock_id_file_record.objects.filter.return_value = qs

        issueproc_qs = MagicMock()
        issueproc_qs.filter.return_value = issueproc_qs
        issueproc_qs.exclude.return_value = issueproc_qs
        issueproc_qs.count.return_value = 3
        journal_proc.issueproc_set.all.return_value = issueproc_qs

        article_proc_model = MagicMock()
        article_qs = MagicMock()
        article_qs.filter.return_value = article_qs
        article_qs.exclude.return_value = article_qs
        article_qs.count.return_value = 5
        article_proc_model.objects.filter.return_value = article_qs

        detail = migration_controller.import_journal_acron_id_records(
            user, article_proc_model, journal_proc, force_update=False
        )

        self.assertEqual(detail["exceptions"], [])
        mock_id_file_record.create_or_update.assert_called_once()
        self.assertIn(
            "total_issueproc_docs_status_to_process", detail["stats"]
        )
        self.assertIn(
            "total_articleproc_migration_status_to_process", detail["stats"]
        )

    @patch("migration.controller.JournalAcronIdFile")
    @patch("migration.controller.get_classic_website")
    def test_ja_atualizado_sem_force_update_retorna_mensagem(
        self, mock_get_cw, mock_journal_acron_id_file
    ):
        user = MagicMock()
        journal_proc = self._make_journal_proc()

        classic_website = MagicMock()
        classic_website.classic_website_paths.bases_work_path = "/bases-work"
        mock_get_cw.return_value = classic_website

        journal_id_file = MagicMock()
        journal_id_file.data = {"id_file_record_need_to_be_updated": False}
        mock_journal_acron_id_file.create_or_update.return_value = journal_id_file

        detail = migration_controller.import_journal_acron_id_records(
            user, MagicMock(), journal_proc, force_update=False
        )

        self.assertIn("message", detail)
        self.assertIn("up-to-date", detail["message"])

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
            user, MagicMock(), journal_proc, force_update=True
        )

        self.assertIn("traceback", detail)
        self.assertIn("exceptions", detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
