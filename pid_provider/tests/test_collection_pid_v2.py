"""
Testes para periódicos presentes em mais de uma coleção com PIDs
diferentes (e, consequentemente, artigos com PIDs v2 diferentes).

Ex.: Psicologia USP
- scl: acron=pusp, pid=0103-6564, artigo S0103-65642009000300003
- psi: acron=psicousp, pid=1678-5177, artigo S1678-51772009000300003
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from collection.models import Collection
from journal.models import Journal, OfficialJournal
from pid_provider.models import (
    CollectionPidV2,
    OtherPid,
    PidProviderXML,
    XMLVersion,
    get_journal_collections,
    get_journal_pid_from_v2,
)
from proc.models import JournalProc

User = get_user_model()

SCL_V2 = "S0103-65642009000300003"
PSI_V2 = "S1678-51772009000300003"
ISSN_PRINT = "0103-6564"
ISSN_ELECTRONIC = "1678-5177"


def make_xml_adapter(v2, v3="V3-PSICOUSP-0000000001"):
    xml_with_pre = MagicMock(name="xml_with_pre")
    xml_with_pre.v2 = v2
    xml_with_pre.v3 = v3
    xml_with_pre.aop_pid = None
    xml_with_pre.readable_data = {"article_titles": ["Titulo"]}
    xml_with_pre.body_fragment_fingerprint = "fingerprint"
    xml_with_pre.get_complete_publication_date.return_value = "2009-12-01"

    adapter = MagicMock(name="xml_adapter")
    adapter.xml_with_pre = xml_with_pre
    adapter.v2 = v2
    adapter.v3 = v3
    adapter.aop_pid = None
    adapter.sps_pkg_name = "0103-6564-pusp-20-03-0003"
    adapter.article_pub_year = "2009"
    adapter.fpage = "3"
    adapter.fpage_seq = None
    adapter.lpage = "20"
    adapter.main_doi = None
    adapter.elocation_id = None
    adapter.z_surnames = "surnames"
    adapter.z_collab = None
    adapter.z_links = None
    adapter.journal_issn_print = ISSN_PRINT
    adapter.journal_issn_electronic = ISSN_ELECTRONIC
    adapter.volume = "20"
    adapter.number = "3"
    adapter.suppl = None
    adapter.pub_year = "2009"
    return adapter


class GetJournalPidFromV2Test(SimpleTestCase):
    def test_returns_journal_pid(self):
        self.assertEqual(get_journal_pid_from_v2(SCL_V2), "0103-6564")

    def test_returns_none_for_invalid_pid(self):
        self.assertIsNone(get_journal_pid_from_v2(None))
        self.assertIsNone(get_journal_pid_from_v2("S0103-6564"))


class MultiCollectionJournalTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="multicol", password="x")
        self.scl = Collection.objects.create(acron="scl", creator=self.user)
        self.psi = Collection.objects.create(acron="psi", creator=self.user)
        official_journal = OfficialJournal.objects.create(
            title="Psicologia USP",
            issn_print=ISSN_PRINT,
            issn_electronic=ISSN_ELECTRONIC,
            creator=self.user,
        )
        journal = Journal.objects.create(
            official_journal=official_journal, creator=self.user
        )
        JournalProc.objects.create(
            journal=journal,
            collection=self.scl,
            acron="pusp",
            pid=ISSN_PRINT,
            creator=self.user,
        )
        JournalProc.objects.create(
            journal=journal,
            collection=self.psi,
            acron="psicousp",
            pid=ISSN_ELECTRONIC,
            creator=self.user,
        )

    def save(self, registered, v2):
        with patch.object(PidProviderXML, "_add_current_version"):
            return PidProviderXML._save(registered, make_xml_adapter(v2), self.user)


class GetJournalCollectionsTest(MultiCollectionJournalTestBase):
    def test_returns_acron_and_pid_by_collection(self):
        items = get_journal_collections(ISSN_PRINT, ISSN_ELECTRONIC)
        result = {
            (item["collection"].acron, item["journal_acron"], item["journal_pid"])
            for item in items
        }
        self.assertEqual(
            result,
            {("scl", "pusp", ISSN_PRINT), ("psi", "psicousp", ISSN_ELECTRONIC)},
        )

    def test_returns_empty_list_without_issn(self):
        self.assertEqual(get_journal_collections(None, None), [])


class IsPidV2FromAnotherCollectionTest(MultiCollectionJournalTestBase):
    def setUp(self):
        super().setUp()
        self.journal_collections = get_journal_collections(
            ISSN_PRINT, ISSN_ELECTRONIC
        )

    def test_true_for_pid_v2_of_another_collection(self):
        ppx = PidProviderXML(v2=SCL_V2)
        self.assertTrue(
            ppx.is_pid_v2_from_another_collection(PSI_V2, self.journal_collections)
        )

    def test_false_for_same_journal_pid(self):
        # mesmo PID de periódico: correção de pid v2
        ppx = PidProviderXML(v2=SCL_V2)
        self.assertFalse(
            ppx.is_pid_v2_from_another_collection(
                "S0103-65642009000300099", self.journal_collections
            )
        )

    def test_false_for_unknown_journal_pid(self):
        ppx = PidProviderXML(v2=SCL_V2)
        self.assertFalse(
            ppx.is_pid_v2_from_another_collection(
                "S9999-99992009000300003", self.journal_collections
            )
        )

    def test_false_for_equal_or_missing_pid_v2(self):
        ppx = PidProviderXML(v2=SCL_V2)
        self.assertFalse(
            ppx.is_pid_v2_from_another_collection(SCL_V2, self.journal_collections)
        )
        self.assertFalse(
            ppx.is_pid_v2_from_another_collection(None, self.journal_collections)
        )


class SaveMultiCollectionTest(MultiCollectionJournalTestBase):
    def test_keeps_registered_v2_and_registers_v2_by_collection(self):
        registered = self.save(None, SCL_V2)
        self.assertEqual(registered.v2, SCL_V2)

        registered = self.save(registered, PSI_V2)
        registered.refresh_from_db()

        # v2 principal não muda
        self.assertEqual(registered.v2, SCL_V2)
        # não é tratado como mudança de pid v2
        self.assertFalse(
            OtherPid.objects.filter(
                pid_provider_xml=registered, pid_type="pid_v2"
            ).exists()
        )
        items = {
            (item.collection.acron, item.journal_acron, item.pid_v2)
            for item in CollectionPidV2.objects.filter(pid_provider_xml=registered)
        }
        self.assertEqual(
            items,
            {("scl", "pusp", SCL_V2), ("psi", "psicousp", PSI_V2)},
        )
        self.assertEqual(
            registered.data["collection_pids_v2"], {"scl": SCL_V2, "psi": PSI_V2}
        )

    def test_registering_again_does_not_duplicate(self):
        registered = self.save(None, SCL_V2)
        registered = self.save(registered, PSI_V2)
        registered = self.save(registered, SCL_V2)
        registered = self.save(registered, PSI_V2)
        registered.refresh_from_db()

        self.assertEqual(registered.v2, SCL_V2)
        self.assertEqual(
            CollectionPidV2.objects.filter(pid_provider_xml=registered).count(), 2
        )

    def test_pid_v2_correction_of_same_journal_still_changes_v2(self):
        registered = self.save(None, SCL_V2)
        # OtherPid requer a versão do XML
        registered.current_version = XMLVersion.objects.create(
            pid_provider_xml=registered, creator=self.user
        )
        registered.save()
        fixed_v2 = "S0103-65642009000300099"
        registered = self.save(registered, fixed_v2)
        registered.refresh_from_db()

        self.assertEqual(registered.v2, fixed_v2)
        self.assertTrue(
            OtherPid.objects.filter(
                pid_provider_xml=registered, pid_type="pid_v2", pid_in_xml=SCL_V2
            ).exists()
        )
        self.assertEqual(
            CollectionPidV2.objects.get(
                pid_provider_xml=registered, collection=self.scl
            ).pid_v2,
            fixed_v2,
        )


class FindByCollectionPidV2Test(MultiCollectionJournalTestBase):
    def setUp(self):
        super().setUp()
        registered = self.save(None, SCL_V2)
        self.registered = self.save(registered, PSI_V2)

    def test_is_registered_pid_v2(self):
        self.assertTrue(PidProviderXML._is_registered_pid(v2=PSI_V2))
        self.assertTrue(PidProviderXML._is_registered_pid(v2=SCL_V2))

    def test_select_records_finds_by_pid_v2_of_another_collection(self):
        xml_adapter = make_xml_adapter(PSI_V2, v3=None)
        with patch("pid_provider.models.QueryBuilderPidProviderXML") as qbuilder_cls:
            from pid_provider.query_params import QueryBuilderPidProviderXML

            qbuilder = qbuilder_cls.return_value
            qbuilder.identifier_queries = QueryBuilderPidProviderXML.identifier_queries.fget(
                MagicMock(xml_adapter=xml_adapter, adapter_data={})
            )
            label, results = next(PidProviderXML.select_records(xml_adapter))

        self.assertEqual(label, "ids")
        self.assertEqual(results, [self.registered])


class MainCollectionPidV2Test(MultiCollectionJournalTestBase):
    """
    O pid v2 principal (PidProviderXML.v2) é o da coleção principal
    (network_classification="scielonetwork")
    """

    def setUp(self):
        super().setUp()
        self.scl.network_classification = "scielonetwork"
        self.scl.save()
        self.psi.network_classification = "thematic"
        self.psi.save()

    def test_get_journal_collections_indicates_main_collection(self):
        items = get_journal_collections(ISSN_PRINT, ISSN_ELECTRONIC)
        result = {item["collection"].acron: item["is_main"] for item in items}
        self.assertEqual(result, {"scl": True, "psi": False})

    def test_main_collection_v2_replaces_v2_of_another_collection(self):
        # registrado primeiro pela coleção temática
        registered = self.save(None, PSI_V2)
        self.assertEqual(registered.v2, PSI_V2)

        registered = self.save(registered, SCL_V2)
        registered.refresh_from_db()

        self.assertEqual(registered.v2, SCL_V2)
        self.assertFalse(
            OtherPid.objects.filter(
                pid_provider_xml=registered, pid_type="pid_v2"
            ).exists()
        )
        self.assertEqual(
            registered.collection_pids_v2_data, {"scl": SCL_V2, "psi": PSI_V2}
        )

    def test_v2_of_another_collection_does_not_replace_main_collection_v2(self):
        registered = self.save(None, SCL_V2)
        registered = self.save(registered, PSI_V2)
        registered.refresh_from_db()

        self.assertEqual(registered.v2, SCL_V2)

    def test_records_previous_v2_when_main_v2_is_replaced(self):
        # registro anterior à existência de CollectionPidV2
        registered = self.save(None, PSI_V2)
        CollectionPidV2.objects.all().delete()

        registered = self.save(registered, SCL_V2)

        self.assertEqual(
            registered.collection_pids_v2_data, {"scl": SCL_V2, "psi": PSI_V2}
        )

    def test_get_main_pid_v2(self):
        journal_collections = get_journal_collections(ISSN_PRINT, ISSN_ELECTRONIC)
        self.assertEqual(
            PidProviderXML(v2=PSI_V2).get_main_pid_v2(SCL_V2, journal_collections),
            SCL_V2,
        )
        self.assertEqual(
            PidProviderXML(v2=SCL_V2).get_main_pid_v2(PSI_V2, journal_collections),
            SCL_V2,
        )
        # correção de pid v2: o do XML prevalece
        self.assertIsNone(
            PidProviderXML(v2=SCL_V2).get_main_pid_v2(
                "S0103-65642009000300099", journal_collections
            )
        )


class DataToCompareMultiCollectionTest(MultiCollectionJournalTestBase):
    def setUp(self):
        super().setUp()
        registered = self.save(None, SCL_V2)
        self.registered = self.save(registered, PSI_V2)

    def test_pid_v2_list_has_main_v2_first(self):
        self.assertEqual(self.registered.pid_v2_list, [SCL_V2, PSI_V2])

    def test_data_to_compare_uses_all_pids_v2_when_unreadable(self):
        with patch.object(PidProviderXML, "get_readable_data", return_value={}):
            data = self.registered.data_to_compare
        self.assertEqual(data["pid_v2"], [SCL_V2, PSI_V2])

    def test_compare_matches_pid_v2_of_another_collection(self):
        from pid_provider.query_params import compare

        with patch.object(PidProviderXML, "get_readable_data", return_value={}):
            registered_data = self.registered.data_to_compare
        input_data = dict(registered_data)
        input_data["pid_v2"] = PSI_V2

        result = compare(registered_data, input_data)
        pid_v2_item = [item for item in result["items"] if item["label"] == "pid_v2"][0]
        self.assertEqual(pid_v2_item["score"], 1)
