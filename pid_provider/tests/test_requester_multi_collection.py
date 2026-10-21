"""
Testes de integração do fluxo do Upload (PidRequester: Core + registro local)
para o mesmo artigo em coleções diferentes.

O XML de psi já está registrado. Então é registrado o XML de scl com os
mesmos dados, exceto:
- sem pid v3 (como os XML obtidos na migração)
- pid v2 de scl
- coleção scl (custom-meta)

A resposta do Core é simulada: como o código do pid provider do Core é o
mesmo do Upload, ele identifica o documento pelos metadados e retorna o
mesmo pid v3 do XML de psi.
"""

from unittest.mock import MagicMock, PropertyMock, patch
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre
from wagtail.admin.admin_url_finder import AdminURLFinder

from pid_provider.client import PidProviderAPIClient
from pid_provider.models import CollectionPidV2, OtherPid, PidProviderXML
from pid_provider.requester import PidRequester
from pid_provider.tests.test_register_multi_collection import (
    PSI_V2,
    SCL_V2,
    TITLE,
    XML_TEMPLATE,
    RegisterSameArticleInDifferentCollectionsTestBase,
    make_xml_with_pre,
    psi_xml,
    scl_xml,
)

User = get_user_model()


class FakeCore:
    """
    Simula o pid provider do Core: guarda o XML recebido e responde com o
    pid v3 do documento já registrado
    """

    def __init__(self, pid_v3):
        self.pid_v3 = pid_v3
        self.received = []

    def post_xml(self, zip_xml_file_path, token, timeout):
        with ZipFile(zip_xml_file_path) as zf:
            content = zf.read(zf.namelist()[0]).decode("utf-8")
        xml_with_pre = list(XMLWithPre.create(xml_content=content))[0]
        self.received.append(xml_with_pre)

        xml_changed = {}
        if xml_with_pre.v3 != self.pid_v3:
            xml_changed["pid_v3"] = self.pid_v3
        return [
            {
                "v3": self.pid_v3,
                "v2": xml_with_pre.v2,
                "aop_pid": xml_with_pre.aop_pid,
                "xml_changed": xml_changed,
            }
        ]


class RequestPidForXMLOfAnotherCollectionTest(
    RegisterSameArticleInDifferentCollectionsTestBase
):
    def setUp(self):
        super().setUp()
        # XML de psi já registrado
        response = self.register(psi_xml(), "psi")
        self.psi_v3 = response["v3"]

    def request_pid(self, xml_with_pre, xml_name):
        xml_with_pre.xml_name = xml_name
        core = FakeCore(self.psi_v3)
        with patch.object(
            PidProviderAPIClient, "enabled", new_callable=PropertyMock
        ) as enabled, patch.object(
            PidProviderAPIClient, "_get_token", return_value="token"
        ), patch.object(
            PidProviderAPIClient, "_post_xml", side_effect=core.post_xml
        ):
            enabled.return_value = True
            response = PidRequester().request_pid_for_xml_with_pre(
                xml_with_pre,
                xml_with_pre.filename,
                self.user,
                origin_date="2026-01-01",
                article_proc=MagicMock(),
            )
        self.assertIsNone(
            response.get("error_type"),
            f"{response.get('error_msg')} {response.get('traceback')}",
        )
        return response, core

    def test_xml_sent_to_core_has_no_pid_v3(self):
        xml_with_pre = scl_xml()
        self.assertIsNone(xml_with_pre.v3)

        response, core = self.request_pid(xml_with_pre, "scl")

        self.assertEqual(len(core.received), 1)
        sent = core.received[0]
        self.assertIsNone(sent.v3)
        self.assertEqual(sent.v2, SCL_V2)
        self.assertEqual(sent.collection, "scl")

    def test_xml_receives_pid_v3_of_the_registered_article(self):
        xml_with_pre = scl_xml()

        response, core = self.request_pid(xml_with_pre, "scl")

        self.assertEqual(xml_with_pre.v3, self.psi_v3)
        self.assertEqual(response["v3"], self.psi_v3)
        # a resposta traz o pid v2 do XML recebido
        self.assertEqual(response["v2"], SCL_V2)
        self.assertTrue(response["registered_in_core"])

    def test_article_is_registered_once_with_pids_v2_of_both_collections(self):
        self.request_pid(scl_xml(), "scl")

        self.assertEqual(PidProviderXML.objects.count(), 1)
        registered = PidProviderXML.objects.get()
        self.assertEqual(registered.v3, self.psi_v3)
        # pid v2 principal é o da coleção principal (scl)
        self.assertEqual(registered.v2, SCL_V2)
        # painel "PID v2 by collection"
        self.assert_pids_v2_by_collection(registered)
        # nenhum pid mudou
        self.assertFalse(OtherPid.objects.filter(pid_provider_xml=registered).exists())

    def test_admin_panel_lists_pids_v2_of_both_collections(self):
        self.request_pid(scl_xml(), "scl")
        registered = PidProviderXML.objects.get()

        # página de edição do PidProviderXML no admin (Wagtail)
        admin = User.objects.create_superuser(
            username="multicol-admin", email="admin@example.org", password="x"
        )
        self.client.force_login(admin)
        edit_url = AdminURLFinder(admin).get_edit_url(registered)
        self.assertIsNotNone(edit_url)
        response = self.client.get(edit_url)
        self.assertEqual(response.status_code, 200)

        # painel "PID v2 by collection" (InlinePanel("collection_pids_v2"))
        formset = response.context["form"].formsets["collection_pids_v2"]
        self.assertCountEqual(
            [
                (form.instance.collection.acron, form.instance.pid_v2)
                for form in formset.forms
            ],
            [("scl", SCL_V2), ("psi", PSI_V2)],
        )
        content = response.content.decode("utf-8")
        self.assertIn("PID v2 by collection", content)
        # o pid v2 de psi só aparece no painel; o de scl aparece também em v2
        self.assertIn(PSI_V2, content)
        self.assertGreaterEqual(content.count(SCL_V2), 2)

        # painel "Other PID" vazio
        self.assertEqual(len(response.context["form"].formsets["other_pid"].forms), 0)

    def spy_select_records(self):
        """
        Registra, para cada chamada de PidProviderXML.select_records, as
        estratégias avaliadas e seus candidatos. select_record consome o
        generator até encontrar o registro, então a última estratégia
        avaliada é a que identificou o documento
        """
        calls = []
        original = PidProviderXML.select_records

        def select_records(xml_adapter):
            call = {"v2": xml_adapter.v2, "v3": xml_adapter.v3, "strategies": []}
            calls.append(call)
            for label, results in original(xml_adapter):
                call["strategies"].append((label, [item.id for item in results]))
                yield label, results

        return calls, patch.object(
            PidProviderXML, "select_records", side_effect=select_records
        )

    def assert_identified_by_metadata(self, call, registered):
        strategies = dict(call["strategies"])
        # a busca por identificadores não traz candidatos
        self.assertEqual(strategies["ids"], [])
        # o documento é identificado pelos metadados
        label, candidates = call["strategies"][-1]
        self.assertIn(
            label,
            ("journal-issue-article-strict", "journal-issue-article-flexible"),
        )
        self.assertEqual(candidates, [registered.id])

    def assert_no_common_identifier(self, registered, xml_with_pre):
        # o registro de psi não tem o pid v2 de scl
        self.assertNotEqual(registered.v2, SCL_V2)
        self.assertNotIn(SCL_V2, registered.pid_v2_list)
        # o registro tem dados legíveis: pid_v2 não entra na comparação
        self.assertNotIn("pid_v2", registered.data_to_compare)
        # o XML de scl não tem pid v3, aop_pid nem DOI
        self.assertEqual(xml_with_pre.v2, SCL_V2)
        self.assertIsNone(xml_with_pre.v3)
        self.assertIsNone(xml_with_pre.aop_pid)
        self.assertIsNone(xml_with_pre.main_doi)

    def test_core_identifies_the_article_by_metadata(self):
        """
        O pid provider do Core tem o mesmo código: recebe o XML de scl sem
        pid v3 e identifica o documento pelos metadados
        """
        psi_registered = PidProviderXML.objects.get()
        xml_with_pre = scl_xml()
        self.assert_no_common_identifier(psi_registered, xml_with_pre)

        calls, spy = self.spy_select_records()
        with spy:
            response = self.register(xml_with_pre, "scl")

        self.assertEqual(len(calls), 1)
        self.assert_identified_by_metadata(calls[0], psi_registered)
        self.assertEqual(response["event_status"], "updated")
        self.assertEqual(response["v3"], self.psi_v3)
        self.assertEqual(response["xml_changed"], {"pid_v3": self.psi_v3})

    def test_upload_identifies_the_article_by_metadata_before_core(self):
        psi_registered = PidProviderXML.objects.get()
        xml_with_pre = scl_xml()
        self.assert_no_common_identifier(psi_registered, xml_with_pre)

        calls, spy = self.spy_select_records()
        with spy:
            self.request_pid(xml_with_pre, "scl")

        self.assertEqual(len(calls), 2)
        # 1) get_registration_demand (is_registered), antes do Core:
        # XML sem pid v3, identificado pelos metadados
        self.assertEqual(calls[0]["v2"], SCL_V2)
        self.assertIsNone(calls[0]["v3"])
        self.assert_identified_by_metadata(calls[0], psi_registered)
        # 2) local_registration (register), depois do Core: XML com o pid
        # v3 retornado pelo Core, identificado por ele
        self.assertEqual(calls[1]["v2"], SCL_V2)
        self.assertEqual(calls[1]["v3"], self.psi_v3)
        self.assertEqual(dict(calls[1]["strategies"])["ids"], [psi_registered.id])

        self.assertEqual(PidProviderXML.objects.get().id, psi_registered.id)

    def test_article_with_different_metadata_is_not_identified(self):
        # mesmo periódico, fascículo e páginas, mas outro artigo
        content = (
            XML_TEMPLATE.format(pid_v2=SCL_V2, journal_acron="pusp")
            .replace(TITLE, "Clínica psicanalítica e instituição hospitalar")
            .replace("Silva", "Pereira")
            .replace("Souza", "Almeida")
            .replace("constituição do sujeito", "prática clínica em hospitais")
            .replace("lugar do outro", "papel da equipe multiprofissional")
        )
        response = PidProviderXML.register(
            make_xml_with_pre(SCL_V2, "pusp", "scl", content),
            "scl",
            self.user,
            origin_date="2026-01-01",
        )

        self.assertIsNone(response.get("error_type"), response.get("error_msg"))
        self.assertEqual(response["event_status"], "created")
        self.assertEqual(PidProviderXML.objects.count(), 2)
        self.assertNotEqual(response["v3"], self.psi_v3)

    def test_main_collection_xml_becomes_the_current_version(self):
        self.request_pid(scl_xml(), "scl")

        registered = PidProviderXML.objects.get()
        self.assert_current_version_is_from(registered, self.scl)
        self.assertIsNotNone(self.collection_current_version(registered, self.psi))

    def test_registering_psi_again_keeps_main_v2(self):
        self.request_pid(scl_xml(), "scl")
        response, core = self.request_pid(psi_xml(), "psi")

        registered = PidProviderXML.objects.get()
        self.assertEqual(response["v3"], self.psi_v3)
        self.assertEqual(response["v2"], PSI_V2)
        self.assertEqual(registered.v2, SCL_V2)
        self.assertEqual(CollectionPidV2.objects.filter(pid_provider_xml=registered).count(), 2)
        self.assertFalse(OtherPid.objects.filter(pid_provider_xml=registered).exists())
