"""
Testes de integração de PidProviderXML.register com 2 XML que representam
o mesmo artigo em coleções diferentes.

Ex.: Psicologia USP
- scl: acron=pusp, pid=0103-6564, artigo S0103-65642009000300003
- psi: acron=psicousp, pid=1678-5177, artigo S1678-51772009000300003

Os XML têm o mesmo conteúdo, diferem no pid v2 (e no acrônimo do
periódico) e não têm pid v3 (como os XML gerados a partir do site clássico).
"""

from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from collection.models import Collection
from journal.models import Journal, OfficialJournal
from pid_provider.models import CollectionPidV2, OtherPid, PidProviderXML
from proc.models import JournalProc

User = get_user_model()

SCL_V2 = "S0103-65642009000300003"
PSI_V2 = "S1678-51772009000300003"
ISSN_PRINT = "0103-6564"
ISSN_ELECTRONIC = "1678-5177"

XML_TEMPLATE = """<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.1 20151215//EN" "https://jats.nlm.nih.gov/publishing/1.1/JATS-journalpublishing1.dtd">
<article xmlns:mml="http://www.w3.org/1998/Math/MathML" xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article" dtd-version="1.1" specific-use="sps-1.9" xml:lang="pt">
  <front>
    <journal-meta>
      <journal-id journal-id-type="publisher-id">{journal_acron}</journal-id>
      <journal-title-group>
        <journal-title>Psicologia USP</journal-title>
      </journal-title-group>
      <issn pub-type="ppub">0103-6564</issn>
      <issn pub-type="epub">1678-5177</issn>
    </journal-meta>
    <article-meta>
      <article-id specific-use="scielo-v2" pub-id-type="publisher-id">{pid_v2}</article-id>
      <article-id pub-id-type="other">00003</article-id>
      <article-categories>
        <subj-group subj-group-type="heading">
          <subject>Artigos</subject>
        </subj-group>
      </article-categories>
      <title-group>
        <article-title>A constituição do sujeito e o laço social</article-title>
      </title-group>
      <contrib-group>
        <contrib contrib-type="author">
          <name>
            <surname>Silva</surname>
            <given-names>Maria</given-names>
          </name>
        </contrib>
        <contrib contrib-type="author">
          <name>
            <surname>Souza</surname>
            <given-names>João</given-names>
          </name>
        </contrib>
      </contrib-group>
      <pub-date date-type="pub" publication-format="electronic">
        <day>01</day>
        <month>09</month>
        <year>2009</year>
      </pub-date>
      <pub-date date-type="collection" publication-format="electronic">
        <year>2009</year>
      </pub-date>
      <volume>20</volume>
      <issue>3</issue>
      <fpage>333</fpage>
      <lpage>350</lpage>
    </article-meta>
  </front>
  <body>
    <p>Este artigo discute a constituição do sujeito a partir do laço social, considerando as contribuições da psicanálise para a compreensão das relações entre o indivíduo e a cultura contemporânea.</p>
    <p>Discute-se, ainda, o lugar do outro na formação da subjetividade e as consequências clínicas dessa perspectiva.</p>
  </body>
</article>
"""


def make_xml_with_pre(pid_v2, journal_acron):
    xml_content = XML_TEMPLATE.format(pid_v2=pid_v2, journal_acron=journal_acron)
    return list(XMLWithPre.create(xml_content=xml_content))[0]


def scl_xml():
    return make_xml_with_pre(SCL_V2, "pusp")


def psi_xml():
    return make_xml_with_pre(PSI_V2, "psicousp")


class RegisterSameArticleInDifferentCollectionsTestBase(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.override_settings = override_settings(
            MEDIA_ROOT=self.media_directory.name
        )
        self.override_settings.enable()
        self.addCleanup(self.override_settings.disable)
        self.addCleanup(self.media_directory.cleanup)

        self.user = User.objects.create_user(username="multicol-register")
        self.scl = Collection.objects.create(
            acron="scl", network_classification="scielonetwork", creator=self.user
        )
        self.psi = Collection.objects.create(
            acron="psi", network_classification="thematic", creator=self.user
        )
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

    def register(self, xml_with_pre, filename):
        response = PidProviderXML.register(
            xml_with_pre, filename, self.user, origin_date="2026-01-01"
        )
        self.assertIsNone(
            response.get("error_type"),
            f"{response.get('error_msg')} {response.get('traceback')}",
        )
        return response

    def assert_same_article_registered_once(self, first, second):
        self.assertEqual(PidProviderXML.objects.count(), 1)
        registered = PidProviderXML.objects.get()
        self.assertEqual(first["v3"], registered.v3)
        self.assertEqual(second["v3"], registered.v3)
        self.assertEqual(first["ppx_id"], second["ppx_id"])
        return registered

    def assert_pids_v2_by_collection(self, registered):
        self.assertEqual(
            registered.collection_pids_v2_data, {"scl": SCL_V2, "psi": PSI_V2}
        )
        self.assertEqual(
            {
                (item.collection.acron, item.journal_acron, item.pid_v2)
                for item in CollectionPidV2.objects.filter(
                    pid_provider_xml=registered
                )
            },
            {("scl", "pusp", SCL_V2), ("psi", "psicousp", PSI_V2)},
        )

    def assert_no_pid_v2_change(self, registered):
        # pid v2 de outra coleção não é mudança de pid v2
        self.assertFalse(
            OtherPid.objects.filter(
                pid_provider_xml=registered, pid_type="pid_v2"
            ).exists()
        )


class RegisterMainCollectionFirstTest(
    RegisterSameArticleInDifferentCollectionsTestBase
):
    """scl (coleção principal) é registrado antes de psi (temática)"""

    def test_second_xml_is_identified_as_the_same_article(self):
        first = self.register(scl_xml(), "scl")
        second = self.register(psi_xml(), "psi")

        self.assertEqual(first["event_status"], "created")
        self.assertEqual(second["event_status"], "updated")
        registered = self.assert_same_article_registered_once(first, second)
        # xml de psi recebe o mesmo pid v3
        self.assertEqual(second["xml_changed"], {"pid_v3": registered.v3})

    def test_main_v2_is_kept_and_v2_by_collection_is_registered(self):
        self.register(scl_xml(), "scl")
        second = self.register(psi_xml(), "psi")

        registered = PidProviderXML.objects.get()
        self.assertEqual(registered.v2, SCL_V2)
        self.assertEqual(second["v2"], SCL_V2)
        self.assertEqual(
            second["collection_pids_v2"], {"scl": SCL_V2, "psi": PSI_V2}
        )
        self.assert_pids_v2_by_collection(registered)
        self.assert_no_pid_v2_change(registered)

    def test_registering_alternately_keeps_main_v2(self):
        responses = [
            self.register(scl_xml(), "scl"),
            self.register(psi_xml(), "psi"),
            self.register(scl_xml(), "scl"),
            self.register(psi_xml(), "psi"),
        ]

        registered = PidProviderXML.objects.get()
        self.assertEqual({item["v3"] for item in responses}, {registered.v3})
        self.assertEqual(registered.v2, SCL_V2)
        self.assertEqual(CollectionPidV2.objects.count(), 2)
        self.assert_no_pid_v2_change(registered)

    def test_is_registered_identifies_xml_of_both_collections(self):
        created = self.register(scl_xml(), "scl")
        self.register(psi_xml(), "psi")

        for xml_with_pre in (scl_xml(), psi_xml()):
            with self.subTest(v2=xml_with_pre.v2):
                response = PidProviderXML.is_registered(xml_with_pre)
                self.assertTrue(response["registered"])
                self.assertEqual(response["v3"], created["v3"])
                self.assertEqual(response["v2"], SCL_V2)

    def test_pids_v2_of_both_collections_are_not_free(self):
        self.register(scl_xml(), "scl")
        self.register(psi_xml(), "psi")

        self.assertTrue(PidProviderXML._is_registered_pid(v2=SCL_V2))
        self.assertTrue(PidProviderXML._is_registered_pid(v2=PSI_V2))


class RegisterThematicCollectionFirstTest(
    RegisterSameArticleInDifferentCollectionsTestBase
):
    """psi (temática) é registrado antes de scl (coleção principal)"""

    def test_second_xml_is_identified_as_the_same_article(self):
        first = self.register(psi_xml(), "psi")
        second = self.register(scl_xml(), "scl")

        self.assertEqual(first["event_status"], "created")
        self.assertEqual(second["event_status"], "updated")
        self.assert_same_article_registered_once(first, second)

    def test_main_collection_v2_becomes_the_main_v2(self):
        first = self.register(psi_xml(), "psi")
        self.assertEqual(first["v2"], PSI_V2)

        second = self.register(scl_xml(), "scl")

        registered = PidProviderXML.objects.get()
        self.assertEqual(registered.v2, SCL_V2)
        self.assertEqual(second["v2"], SCL_V2)
        self.assert_pids_v2_by_collection(registered)
        self.assert_no_pid_v2_change(registered)

    def test_thematic_collection_does_not_replace_main_v2_afterwards(self):
        self.register(psi_xml(), "psi")
        self.register(scl_xml(), "scl")
        self.register(psi_xml(), "psi")

        registered = PidProviderXML.objects.get()
        self.assertEqual(registered.v2, SCL_V2)
        self.assert_pids_v2_by_collection(registered)


class RegisterWithoutMainCollectionTest(
    RegisterSameArticleInDifferentCollectionsTestBase
):
    """nenhuma das coleções é classificada como scielonetwork"""

    def setUp(self):
        super().setUp()
        Collection.objects.update(network_classification=None)

    def test_first_registered_v2_is_kept(self):
        self.register(psi_xml(), "psi")
        self.register(scl_xml(), "scl")

        registered = PidProviderXML.objects.get()
        self.assertEqual(registered.v2, PSI_V2)
        self.assert_pids_v2_by_collection(registered)
        self.assert_no_pid_v2_change(registered)
