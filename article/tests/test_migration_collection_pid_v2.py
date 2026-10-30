"""
Migração de dados para o vínculo de SPSPkg e Article com o documento na
coleção (CollectionPidV2):

- package 0011_spspkg_collection_pid_v2
- article 0013_article_collection_pid_v2
- package 0012_remove_spspkg_ppx_collection_pids
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [
    ("package", "0010_spspkg_collection"),
    ("article", "0012_article_data_availability_status"),
    # estado do projeto inclui os modelos usados nos dados de teste
    ("pid_provider", "0018_collectionpidv2"),
    ("proc", "0015_alter_articleproc_migration_status_and_more"),
    ("journal", "0016_update_journal_acron_from_journal_proc"),
]
AFTER = [
    ("package", "0012_remove_spspkg_ppx_collection_pids"),
    ("article", "0013_article_collection_pid_v2"),
]

SCL_V2 = "S0103-65642009000300003"
PSI_V2 = "S1678-51772009000300003"


class CollectionPidV2DataMigrationTest(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        apps = self.migrate(BEFORE)
        self.addCleanup(self.migrate, AFTER)

        User = apps.get_model("users", "User")
        Collection = apps.get_model("collection", "Collection")
        Journal = apps.get_model("journal", "Journal")
        JournalProc = apps.get_model("proc", "JournalProc")
        ArticleProc = apps.get_model("proc", "ArticleProc")
        PidProviderXML = apps.get_model("pid_provider", "PidProviderXML")
        CollectionPidV2 = apps.get_model("pid_provider", "CollectionPidV2")
        SPSPkg = apps.get_model("package", "SPSPkg")
        Article = apps.get_model("article", "Article")

        user = User.objects.create(username="migration")
        scl = Collection.objects.create(acron="scl", creator=user)
        psi = Collection.objects.create(acron="psi", creator=user)
        journal = Journal.objects.create(creator=user)
        JournalProc.objects.create(journal=journal, collection=scl, acron="pusp", creator=user)
        JournalProc.objects.create(journal=journal, collection=psi, acron="psicousp", creator=user)
        other_journal = Journal.objects.create(creator=user)
        JournalProc.objects.create(
            journal=other_journal, collection=scl, acron="other", creator=user
        )

        ppx = PidProviderXML.objects.create(creator=user, v3="V3")
        ppx_other = PidProviderXML.objects.create(creator=user, v3="V3-OTHER")
        ppx_by_pid_v3 = PidProviderXML.objects.create(creator=user, v3="V3-BY-PID-V3")
        # registro já existente do documento em scl
        self.registered_scl_id = CollectionPidV2.objects.create(
            creator=user, pid_provider_xml=ppx, collection=scl, pid_v2=SCL_V2
        ).id

        def pkg(name, **kwargs):
            return SPSPkg.objects.create(creator=user, sps_pkg_name=name, **kwargs)

        # pacote mais antigo do mesmo documento em scl
        pkg("scl-old", ppx=ppx, collection=scl, pid_v2=SCL_V2, pid_v3="V3")
        pkg("scl", ppx=ppx, collection=scl, pid_v2=SCL_V2, pid_v3="V3")
        # sem coleção, mas referenciado por ArticleProc de psi
        psi_pkg = pkg("psi", ppx=ppx, pid_v2=PSI_V2, pid_v3="V3")
        ArticleProc.objects.create(creator=user, collection=psi, sps_pkg=psi_pkg, pid=PSI_V2)
        # sem coleção identificável: ArticleProc de mais de uma coleção
        shared = pkg("shared", ppx=ppx_other, pid_v2="S-SHARED", pid_v3="V3-OTHER")
        ArticleProc.objects.create(creator=user, collection=scl, sps_pkg=shared, pid="a")
        ArticleProc.objects.create(creator=user, collection=psi, sps_pkg=shared, pid="b")
        # sem ppx
        pkg("no-ppx", collection=scl, pid_v2="S-NO-PPX")

        Article.objects.create(
            creator=user, pid_v3="V3", pid_v2=SCL_V2, journal=journal,
            sps_pkg=SPSPkg.objects.get(sps_pkg_name="scl"),
        )
        # sem pacote: identificado por pp_xml e pela coleção única do periódico
        Article.objects.create(
            creator=user, pid_v3="V3-PP-XML", pid_v2="S-PP-XML",
            journal=other_journal, pp_xml=ppx_other,
        )
        # sem pacote e sem pp_xml: identificado pelo pid_v3
        Article.objects.create(
            creator=user, pid_v3="V3-BY-PID-V3", pid_v2="S-BY-PID-V3",
            journal=other_journal,
        )
        # coleção não identificável (periódico em mais de uma coleção)
        Article.objects.create(
            creator=user, pid_v3="V3-NO-COLLECTION", journal=journal, pp_xml=ppx,
        )

        self.apps = self.migrate(AFTER)

    def test_sps_pkg_is_linked_to_the_document_in_the_collection(self):
        SPSPkg = self.apps.get_model("package", "SPSPkg")
        linked = {
            item.sps_pkg_name: (
                item.collection_pid_v2.collection.acron,
                item.collection_pid_v2.pid_v2,
                item.collection_pid_v2.pid_provider_xml.v3,
            )
            for item in SPSPkg.objects.filter(collection_pid_v2__isnull=False)
        }
        self.assertEqual(
            linked,
            {
                "scl": ("scl", SCL_V2, "V3"),
                "psi": ("psi", PSI_V2, "V3"),
            },
        )
        # o registro existente é reaproveitado
        self.assertEqual(
            SPSPkg.objects.get(sps_pkg_name="scl").collection_pid_v2_id,
            self.registered_scl_id,
        )
        # psi: acrônimo do periódico obtido do ArticleProc / JournalProc
        self.assertIsNone(
            SPSPkg.objects.get(sps_pkg_name="psi").collection_pid_v2.journal_acron
        )
        self.assertEqual(
            set(
                SPSPkg.objects.filter(collection_pid_v2__isnull=True).values_list(
                    "sps_pkg_name", flat=True
                )
            ),
            {"scl-old", "shared", "no-ppx"},
        )

    def test_article_is_linked_to_the_document_in_the_collection(self):
        Article = self.apps.get_model("article", "Article")
        linked = {
            item.pid_v3: (
                item.collection_pid_v2.collection.acron,
                item.collection_pid_v2.pid_v2,
                item.collection_pid_v2.pid_provider_xml.v3,
                item.collection_pid_v2.journal_acron,
            )
            for item in Article.objects.filter(collection_pid_v2__isnull=False)
        }
        self.assertEqual(
            linked,
            {
                # pelo pacote
                "V3": ("scl", SCL_V2, "V3", None),
                # criado a partir de pp_xml, pid_v2 e coleção do periódico
                "V3-PP-XML": ("scl", "S-PP-XML", "V3-OTHER", "other"),
                "V3-BY-PID-V3": ("scl", "S-BY-PID-V3", "V3-BY-PID-V3", "other"),
            },
        )
        self.assertEqual(
            list(
                Article.objects.filter(collection_pid_v2__isnull=True).values_list(
                    "pid_v3", flat=True
                )
            ),
            ["V3-NO-COLLECTION"],
        )
