"""
Testes unitários para PidProviderXML.register.

Estratégia
----------
register() é orquestrador: delega a get_records, complete_missing_xml_pids,
is_updated e _save. Os testes isolam register desses colaboradores via mock e
verificam, para cada caminho, DOIS contratos:

  1. o event_status efetivamente gravado em PidProviderXMLRegistration.record
  2. a forma do response retornado

Como register grava SEMPRE (no finally), o ponto de observação central é o
mock de PidProviderXMLRegistration.record: inspecionamos seus kwargs.

Caminhos cobertos (event_status):
  - created     : sem registro existente -> _save cria
  - updated     : registro existente -> _save atualiza
  - skipped     : is_updated retorna data (já atualizado / igual)
  - conflict    : complete_missing_xml_pids levanta PidProviderXMLPidV3ConflictError
  - forbidden   : is_updated levanta ForbiddenPidProviderXMLRegistrationError
  - unmatched   : get_records levanta UnmatchedPidProviderXMLError / MultipleObjectsReturned
  - bad_request : get_records levanta RequiredISSNError etc.
  - error       : exceção inesperada -> UnexpectedEvent + event_status=error

Ajuste os caminhos de import (PATCH_BASE) conforme a estrutura do seu projeto.
"""

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
    # build_readable_data:
    m.authors = {"person": [{"surname": "SILVA"}]}
    m.collab = None
    m.links = []
    m.article_titles_texts = ["Some title"]
    m.partial_body = "corpo parcial"
    return m


class RegisterTestBase(TestCase):
    """
    Mocka todos os colaboradores de register e o gravador de auditoria.
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

        # patch do gravador de auditoria — ponto central de verificação
        self.p_record = patch(f"{PATCH_BASE}.PidProviderXMLRegistration.record")
        self.m_record = self.p_record.start()
        self.addCleanup(self.p_record.stop)

        # build_readable_data é staticmethod; deixamos rodar (usa o xml fake),
        # mas se preferir isolar, dá para mockar também.

    # -- helper de asserção -------------------------------------------------
    def assert_recorded_status(self, expected_status):
        self.assertTrue(
            self.m_record.called, "PidProviderXMLRegistration.record não foi chamado"
        )
        kwargs = self.m_record.call_args.kwargs
        self.assertEqual(kwargs.get("event_status"), expected_status)
        return kwargs


class CreatedPathTest(RegisterTestBase):
    def test_created_when_no_existing_record(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_get.side_effect = PidProviderXML.DoesNotExist
            m_cmp.return_value = {}
            m_upd.return_value = None
            saved = MagicMock(name="saved_ppx")
            saved.data = {"v3": "ABC", "record_status": "created"}
            m_save.return_value = (saved, "created")

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("created")
        self.assertEqual(response.get("v3"), "ABC")
        self.assertNotIn("error_msg", response)


class UpdatedPathTest(RegisterTestBase):
    def test_updated_when_existing_record(self):
        existing = MagicMock(name="existing_ppx")
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_get.return_value = {"registered": existing, "failed": []}
            m_cmp.return_value = {"pid_v3": "NEW"}
            m_upd.return_value = None
            saved = MagicMock(name="saved_ppx")
            saved.data = {"v3": "ABC", "record_status": "updated"}
            m_save.return_value = (saved, "updated")

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        kwargs = self.assert_recorded_status("updated")
        # o evento referencia o objeto salvo
        self.assertIs(kwargs.get("pid_provider_xml"), saved)
        self.assertIn("xml_changed", response)


class SkippedPathTest(RegisterTestBase):
    def test_skipped_returns_data_and_does_not_flag_error(self):
        existing = MagicMock(name="existing_ppx")
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_get.return_value = {"registered": existing, "failed": []}
            m_cmp.return_value = {}
            m_upd.return_value = {"v3": "ABC", "record_status": "updated"}  # já atualizado

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

            # _save NÃO deve ser chamado no skip
            m_save.assert_not_called()

        self.assert_recorded_status("skipped")
        self.assertTrue(response.get("skip_update"))
        # skip é sucesso de negócio: não deve marcar erro
        self.assertNotIn("error_msg", response)


class ConflictPathTest(RegisterTestBase):
    def test_conflict_when_pid_v3_conflict(self):
        existing = MagicMock(name="existing_ppx")
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_get.return_value = {"registered": existing, "failed": []}
            m_cmp.side_effect = PidProviderXMLPidV3ConflictError("conflict!")

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

            m_save.assert_not_called()

        self.assert_recorded_status("conflict")
        self.assertIn("error_msg", response)
        self.assertIn("error_type", response)


class ForbiddenPathTest(RegisterTestBase):
    def test_forbidden_when_aop_over_vor(self):
        existing = MagicMock(name="existing_ppx")
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_get.return_value = {"registered": existing, "failed": []}
            m_cmp.return_value = {}
            m_upd.side_effect = (
                exceptions.ForbiddenPidProviderXMLRegistrationError("forbidden")
            )

            response = PidProviderXML.register(self.xml, "file.xml", self.user)

            m_save.assert_not_called()

        self.assert_recorded_status("forbidden")
        self.assertIn("error_msg", response)


class UnmatchedPathTest(RegisterTestBase):
    def test_unmatched_when_get_records_raises_unmatched(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get:
            m_get.side_effect = exceptions.UnmatchedPidProviderXMLError("unmatched")
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("unmatched")
        self.assertIn("error_msg", response)

    def test_unmatched_when_failed_without_registered(self):
        # get_records retorna dict com failed e sem registered -> register levanta
        # UnmatchedPidProviderXMLError internamente
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get:
            m_get.return_value = {"registered": None, "failed": [{"id": 1}]}
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("unmatched")

    def test_multiple_objects_returned_is_unmatched(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get:
            m_get.side_effect = PidProviderXML.MultipleObjectsReturned()
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("unmatched")


class BadRequestPathTest(RegisterTestBase):
    """
    ATENÇÃO — MUDANÇA DE CONTRATO:
    Na versão atual, as exceções de bad_request NÃO propagam mais ao chamador;
    viram response com event_status='bad_request'. Estes testes DOCUMENTAM o
    comportamento atual. Se a decisão for propagar (opção B), troque por
    assertRaises e remova o return no finally.
    """

    def test_required_issn_becomes_response_not_raise(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get:
            m_get.side_effect = (
                exceptions.RequiredISSNErrorToGetPidProviderXMLError("no issn")
            )
            # NÃO levanta — retorna response
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("bad_request")
        self.assertIn("error_msg", response)

    def test_required_pub_year_becomes_response(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get:
            m_get.side_effect = (
                exceptions.RequiredPublicationYearErrorToGetPidProviderXMLError("no year")
            )
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("bad_request")

    def test_not_enough_parameters_becomes_response(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get:
            m_get.side_effect = (
                exceptions.NotEnoughParametersToGetPidProviderXMLError("not enough")
            )
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("bad_request")


class ErrorPathTest(RegisterTestBase):
    def test_unexpected_exception_records_error_and_logs_unexpected_event(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get, \
             patch(f"{PATCH_BASE}.UnexpectedEvent.create") as m_unexpected:

            m_get.side_effect = ValueError("algo totalmente inesperado")
            response = PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assert_recorded_status("error")
        self.assertIn("error_msg", response)
        # erro inesperado deve registrar UnexpectedEvent
        m_unexpected.assert_called_once()


class RecordAlwaysCalledTest(RegisterTestBase):
    """Garante a premissa 'grava SEMPRE': record é chamado exatamente 1 vez."""

    def test_record_called_exactly_once_on_success(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp, \
             patch(f"{PATCH_BASE}.PidProviderXML.is_updated") as m_upd, \
             patch(f"{PATCH_BASE}.PidProviderXML._save") as m_save:

            m_get.side_effect = PidProviderXML.DoesNotExist
            m_cmp.return_value = {}
            m_upd.return_value = None
            saved = MagicMock()
            saved.data = {"v3": "ABC"}
            m_save.return_value = (saved, "created")

            PidProviderXML.register(self.xml, "file.xml", self.user)

        self.assertEqual(self.m_record.call_count, 1)

    def test_record_called_exactly_once_on_conflict(self):
        with patch(f"{PATCH_BASE}.PidProviderXML.get_records") as m_get, \
             patch(f"{PATCH_BASE}.PidProviderXML.complete_missing_xml_pids") as m_cmp:
            m_get.return_value = {"registered": MagicMock(), "failed": []}
            m_cmp.side_effect = PidProviderXMLPidV3ConflictError("x")
            PidProviderXML.register(self.xml, "file.xml", self.user)

        # antes havia risco de gravar 2x (except + finally); deve ser 1
        self.assertEqual(self.m_record.call_count, 1)