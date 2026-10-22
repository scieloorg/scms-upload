"""Desfechos do registro e acionamento da auditoria do PID Provider."""

from unittest.mock import patch, MagicMock

from django.test import TestCase

from pid_provider import exceptions
from pid_provider.models import (
    PidProviderXML,
    PidProviderXMLPidV3ConflictError,
)

# Caminho do módulo onde register está definido (para os patches "where used").
PATCH_BASE = "pid_provider.models"


def make_xml_with_pre(**overrides):
    """
    XMLWithPre falso, com os atributos que register/build_readable_data tocam.
    """
    m = MagicMock(name="xml_with_pre")
    m.data = {"pid_v3": overrides.get("v3"), "sps_pkg_name": "pkg-fake"}
    m.sps_pkg_name = overrides.get("sps_pkg_name", "pkg-fake")
    m.authors = {"person": [{"surname": "SILVA"}]}
    m.collab = None
    m.links = []
    m.article_titles_texts = ["Some title"]
    m.partial_body = "corpo parcial"
    return m


class RegisterTestBase(TestCase):
    """
    Mocka os colaboradores de register e o gravador de auditoria.
    Cada teste configura os side_effects/returns conforme o caminho.
    """

    def setUp(self):
        self.user = MagicMock(name="user")
        self.xml = make_xml_with_pre(v3="ABCDEFGHIJKLMNOPQRSTUVW")

        # patch do adapter para não depender de packtools real
        self.p_adapter = patch(
            "packtools.sps.pid_provider.xml_sps_adapter.PidProviderXMLAdapter"
        )
        self.m_adapter_cls = self.p_adapter.start()
        self.m_adapter = self.m_adapter_cls.return_value
        self.m_adapter.data = {"pkg_name": "pkg-fake"}
        self.m_adapter.sps_pkg_name = "pkg-fake"
        self.m_adapter.xml_with_pre = self.xml
        self.addCleanup(self.p_adapter.stop)

        # select_records é um gerador que apenas monta querysets candidatos;
        # quem register() efetivamente usa para decidir o fluxo é
        # select_record (singular). Deixamos select_records "inofensivo"
        # (não é consumido, pois select_record está sempre mockado abaixo).
        self.p_select_records = patch(f"{PATCH_BASE}.PidProviderXML.select_records")
        self.m_select_records = self.p_select_records.start()
        self.m_select_records.return_value = iter([])
        self.addCleanup(self.p_select_records.stop)

        # patch do gravador de auditoria — ponto central de verificação
        self.p_record = patch(f"{PATCH_BASE}.PidProviderXMLRegistration.record")
        self.m_record = self.p_record.start()
        self.addCleanup(self.p_record.stop)

        # Mantém os testes independentes da configuração persistida.
        self.p_setting = patch(f"{PATCH_BASE}.PidProviderSetting.load")
        self.m_setting_load = self.p_setting.start()
        self.m_setting_load.return_value.record_all_registration_events = False
        self.addCleanup(self.p_setting.stop)

    # -- helpers de asserção --------------------------------------------
    def assert_recorded_status(self, expected_status):
        self.assertTrue(
            self.m_record.called, "PidProviderXMLRegistration.record não foi chamado"
        )
        kwargs = self.m_record.call_args.kwargs
        self.assertEqual(kwargs.get("event_status"), expected_status)
        return kwargs

    def assert_not_recorded(self):
        self.m_record.assert_not_called()


# ---------------------------------------------------------------------------
# Caminhos "limpos" (sem ambiguidade, sem erro) -> NÃO devem gravar auditoria
# ---------------------------------------------------------------------------
class CreatedPathTest(RegisterTestBase):
    def test_created_when_no_existing_record_and_no_ambiguity(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            # nenhum "registered" no retorno -> pop KeyError -> sem
            # unmatched_items -> DoesNotExist -> event_status="created"
            m_select.return_value = {}
            m_cmp.return_value = {}
            m_upd.return_value = None
            saved = MagicMock(name="saved_ppx")
            saved.data = {"v3": "ABC", "record_status": "created"}
            m_save.return_value = saved  # objeto direto, não mais tupla

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assertEqual(response.get("event_status"), "created")
        self.assertEqual(response.get("v3"), "ABC")
        self.assertNotIn("error_msg", response)
        # created "limpo": sem matched_items e sem erro -> não grava auditoria
        self.assert_not_recorded()


class UpdatedPathTest(RegisterTestBase):
    def test_updated_when_existing_record_and_no_ambiguity(self):
        existing = MagicMock(name="existing_ppx")
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_select.return_value = {"registered": existing}  # sem matched_items
            m_cmp.return_value = {"pid_v3": "NEW"}
            m_upd.return_value = None
            saved = MagicMock(name="saved_ppx")
            saved.data = {"v3": "ABC", "record_status": "updated"}
            m_save.return_value = saved

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assertEqual(response.get("event_status"), "updated")
        self.assertIn("xml_changed", response)
        # updated "limpo" (match único, sem ambiguidade) -> não grava auditoria
        self.assert_not_recorded()


class SkippedPathTest(RegisterTestBase):
    def test_skipped_returns_data_and_does_not_log_when_clean(self):
        """
        MUDANÇA DE CONTRATO: skip agora é sinalizado por is_updated
        LEVANTANDO exceptions.SkipSavePidProviderXML, não mais retornando
        um dict truthy. register() captura essa exceção, seta
        event_status="skipped" e usa registered.data do objeto JÁ
        EXISTENTE (pois _save nunca roda nesse caminho).
        """
        existing = MagicMock(name="existing_ppx")
        existing.data = {"v3": "ABC", "record_status": "updated"}
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_select.return_value = {"registered": existing}  # sem matched_items
            m_cmp.return_value = {}
            m_upd.side_effect = exceptions.SkipSavePidProviderXML

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

            m_save.assert_not_called()

        self.assertEqual(response.get("event_status"), "skipped")
        self.assertTrue(response.get("skipped"))
        self.assertEqual(response.get("v3"), "ABC")  # veio de existing.data
        self.assertNotIn("error_msg", response)
        # skip "limpo" (sem ambiguidade, sem erro) -> não grava auditoria
        self.assert_not_recorded()


# ---------------------------------------------------------------------------
# Ambiguidade (matched_items presentes) -> DEVE gravar auditoria mesmo sem erro
# ---------------------------------------------------------------------------
class MatchedItemsLoggingTest(RegisterTestBase):
    def test_updated_with_matched_items_logs_audit(self):
        existing = MagicMock(name="existing_ppx")
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_select.return_value = {
                "registered": existing,
                "matched_items": [{"id": 2, "v3": "OTHER"}],
            }
            m_cmp.return_value = {}
            m_upd.return_value = None
            saved = MagicMock(name="saved_ppx")
            saved.data = {"v3": "ABC", "record_status": "updated"}
            m_save.return_value = saved

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        kwargs = self.assert_recorded_status("updated")
        self.assertIs(kwargs.get("pid_provider_xml"), saved)
        self.assertIn("select_record_response", response)

    def test_skipped_with_matched_items_still_logs_audit(self):
        existing = MagicMock(name="existing_ppx")
        existing.data = {"v3": "ABC", "record_status": "updated"}
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_select.return_value = {
                "registered": existing,
                "matched_items": [{"id": 2, "v3": "OTHER"}],
            }
            m_cmp.return_value = {}
            m_upd.side_effect = exceptions.SkipSavePidProviderXML

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

            m_save.assert_not_called()

        # mesmo em skip, se havia ambiguidade, a auditoria é gravada
        self.assert_recorded_status("skipped")


# ---------------------------------------------------------------------------
# Caminhos de erro -> sempre logam (error_type setado no except externo)
# ---------------------------------------------------------------------------
class ConflictPathTest(RegisterTestBase):
    def test_conflict_when_pid_v3_conflict(self):
        existing = MagicMock(name="existing_ppx")
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_select.return_value = {"registered": existing}
            m_cmp.side_effect = PidProviderXMLPidV3ConflictError("conflict!")

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

            m_save.assert_not_called()

        self.assert_recorded_status("conflict")
        self.assertIn("error_msg", response)
        self.assertIn("error_type", response)


class ForbiddenPathTest(RegisterTestBase):
    def test_forbidden_when_aop_over_vor(self):
        """
        CORRIGIDO em relação à rodada anterior: agora existe um
        `try/except ForbiddenPidProviderXMLRegistrationError` envolvendo
        `is_updated()` + `_save()`, que seta event_status="forbidden" e
        RE-LEVANTA a exceção (propaga para o except Exception externo,
        que grava o erro mas preserva event_status="forbidden", já que
        `event_status or "error"` só substitui valores falsy).
        """
        existing = MagicMock(name="existing_ppx")
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_select.return_value = {"registered": existing}
            m_cmp.return_value = {}
            m_upd.side_effect = (
                exceptions.ForbiddenPidProviderXMLRegistrationError("forbidden")
            )

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

            m_save.assert_not_called()

        kwargs = self.assert_recorded_status("forbidden")
        self.assertIn("error_msg", response)
        self.assertEqual(response.get("event_status"), "forbidden")
        self.assertIs(kwargs.get("pid_provider_xml"), existing)


class UnmatchedPathTest(RegisterTestBase):
    def test_unmatched_when_select_record_raises_unmatched(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select:
            m_select.side_effect = exceptions.UnmatchedPidProviderXMLError("unmatched")
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("unmatched")
        self.assertIn("error_msg", response)

    def test_unmatched_candidates_allow_creation_and_trigger_audit(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids"), \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated"), \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as save:
            select.return_value = {"unmatched_items": {"ids": [{"data": {"id": 1}}]}}
            save.return_value.data = {"v3": "NEW"}
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("created")
        self.assertNotIn("error_type", response)
        self.assertEqual(response["v3"], "NEW")
        self.assertIsNone(save.call_args.args[0])
        self.assertIn("unmatched_items", response["select_record_response"])

    def test_multiple_objects_returned_has_distinct_status(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as select:
            select.side_effect = PidProviderXML.MultipleObjectsReturned()
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("multiple")
        self.assertIn("QueryDocumentMultipleObjectsReturnedError", response["error_type"])

    def test_tied_candidates_block_registration_even_when_forced(self):
        selection = {"registered": MagicMock(), "multiple_matched_items": {"ids": [1, 2]}}
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record", return_value=selection), \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as complete, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as save:
            response = PidProviderXML.register(
                self.xml, "file.xml", self.user, force_update=True
            )
            check = PidProviderXML.is_registered(self.xml)

        self.assert_recorded_status("multiple")
        self.assertIn("QueryDocumentMultipleObjectsReturnedError", response["error_type"])
        self.assertIn("QueryDocumentMultipleObjectsReturnedError", check["error_type"])
        self.assertIsNone(self.m_record.call_args.kwargs["pid_provider_xml"])
        complete.assert_not_called()
        save.assert_not_called()


class BadRequestPathTest(RegisterTestBase):
    """
    As exceções de bad_request continuam setando event_status="bad_request"
    explicitamente antes de re-levantar, então esse contrato NÃO mudou.
    """

    def test_required_issn_becomes_response_not_raise(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select:
            m_select.side_effect = (
                exceptions.RequiredISSNErrorToGetPidProviderXMLError("no issn")
            )
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("bad_request")
        self.assertIn("error_msg", response)

    def test_required_pub_year_becomes_response(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select:
            m_select.side_effect = (
                exceptions.RequiredPublicationYearErrorToGetPidProviderXMLError("no year")
            )
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("bad_request")

    def test_not_enough_parameters_becomes_response(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select:
            m_select.side_effect = (
                exceptions.NotEnoughParametersToGetPidProviderXMLError("not enough")
            )
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("bad_request")


class UnexpectedErrorPathTest(RegisterTestBase):
    """
    ATENÇÃO — MUDANÇA DE CONTRATO:
    Agora existe `event_status = event_status or "error"` no `except`
    externo. Se nenhum event_status tinha sido atribuído ainda quando a
    exceção genérica ocorre, o valor gravado passa a ser "error" (fallback).
    Se um status já existia (ex.: "created"), ele é preservado —
    `UnexpectedEvent.create` continua sem ser chamado dentro de register().
    """

    def test_unexpected_exception_before_any_status_set_falls_back_to_error(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select:
            m_select.side_effect = ValueError("falha totalmente inesperada")
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        # fallback: nenhum status tinha sido setado -> "error"
        self.assert_recorded_status("error")
        self.assertIn("error_msg", response)

    def test_unexpected_exception_after_created_keeps_created_status(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp:

            m_select.return_value = {}  # -> DoesNotExist -> event_status="created"
            m_cmp.side_effect = ValueError("algo inesperado depois de created")

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        # event_status permanece "created" (fallback só entra quando é falsy)
        self.assert_recorded_status("created")
        self.assertIn("error_msg", response)
        self.assertEqual(response.get("event_status"), "created")


# ---------------------------------------------------------------------------
# Invariante: quando aplicável, record() é chamado no máximo 1 vez
# (nunca duplicado por causa de except + finally)
# ---------------------------------------------------------------------------
class RecordInvocationInvariantTest(RegisterTestBase):
    def test_record_not_called_on_clean_success(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_select.return_value = {}
            m_cmp.return_value = {}
            m_upd.return_value = None
            saved = MagicMock()
            saved.data = {"v3": "ABC"}
            m_save.return_value = saved

            PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assertEqual(self.m_record.call_count, 0)

    def test_record_called_exactly_once_on_conflict(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp:
            m_select.return_value = {"registered": MagicMock()}
            m_cmp.side_effect = PidProviderXMLPidV3ConflictError("x")
            PidProviderXML.register(self.xml, "file.xml", self.user)

        # antes havia risco de gravar 2x (except interno + finally); deve ser 1
        self.assertEqual(self.m_record.call_count, 1)

    def test_record_called_exactly_once_when_matched_items_present(self):
        existing = MagicMock(name="existing_ppx")
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_select.return_value = {
                "registered": existing,
                "matched_items": [{"id": 2}],
            }
            m_cmp.return_value = {}
            m_upd.return_value = None
            saved = MagicMock()
            saved.data = {"v3": "ABC"}
            m_save.return_value = saved

            PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assertEqual(self.m_record.call_count, 1)

    def test_record_called_exactly_once_on_forbidden(self):
        existing = MagicMock(name="existing_ppx")
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd:

            m_select.return_value = {"registered": existing}
            m_cmp.return_value = {}
            m_upd.side_effect = (
                exceptions.ForbiddenPidProviderXMLRegistrationError("x")
            )
            PidProviderXML.register(self.xml, "file.xml", self.user)

        # o except específico de Forbidden seta status e re-levanta; o
        # except Exception externo não deve gravar de novo
        self.assertEqual(self.m_record.call_count, 1)

    def test_record_called_exactly_once_on_skip(self):
        existing = MagicMock(name="existing_ppx")
        existing.data = {"v3": "ABC"}
        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd:

            m_select.return_value = {
                "registered": existing,
                "matched_items": [{"id": 2}],  # força log para poder contar
            }
            m_cmp.return_value = {}
            m_upd.side_effect = exceptions.SkipSavePidProviderXML
            PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assertEqual(self.m_record.call_count, 1)


# ---------------------------------------------------------------------------
# Configuração opcional: fluxos limpos também podem gerar auditoria
# ---------------------------------------------------------------------------
class RecordAllEventsSettingTest(RegisterTestBase):
    def test_record_called_on_clean_success_when_setting_enabled(self):
        self.m_setting_load.return_value.record_all_registration_events = True

        with patch(f"{PATCH_BASE}.PidProviderXML.select_record") as m_select, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_select.return_value = {}
            m_cmp.return_value = {}
            m_upd.return_value = None
            saved = MagicMock(name="saved_ppx")
            saved.data = {"v3": "ABC"}
            m_save.return_value = saved

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assertEqual(response.get("event_status"), "created")
        self.assert_recorded_status("created")
