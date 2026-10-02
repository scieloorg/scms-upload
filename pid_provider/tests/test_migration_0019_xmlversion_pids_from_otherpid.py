"""
Testes da migração 0019_xmlversion_pids_from_otherpid: os PIDs da versão
atual e os PIDs que mudaram (OtherPid) passam para XMLVersion.pid_v3 e
XMLVersion.pid_v2
"""

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

MIGRATE_FROM = [("pid_provider", "0018_xmlversion_pid_v3_pid_v2_collection")]
MIGRATE_TO = [("pid_provider", "0019_xmlversion_pids_from_otherpid")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


class XMLVersionPidsFromOtherPidMigrationTest(TransactionTestCase):
    """
    Um único teste: migrar para trás e para frente o banco de teste é lento
    """

    def setUp(self):
        apps = migrate(MIGRATE_FROM)
        User = apps.get_model(settings.AUTH_USER_MODEL)
        PidProviderXML = apps.get_model("pid_provider", "PidProviderXML")
        XMLVersion = apps.get_model("pid_provider", "XMLVersion")
        OtherPid = apps.get_model("pid_provider", "OtherPid")

        user = User.objects.create(username="migration-0019")

        def create(v3, v2):
            registered = PidProviderXML.objects.create(creator=user, v3=v3, v2=v2)
            previous = XMLVersion.objects.create(
                creator=user, pid_provider_xml=registered, finger_print=f"{v3}-1"
            )
            current = XMLVersion.objects.create(
                creator=user, pid_provider_xml=registered, finger_print=f"{v3}-2"
            )
            registered.current_version = current
            registered.save()
            return registered, previous, current

        def other_pid(registered, pid_type, pid_in_xml, version):
            return OtherPid.objects.create(
                creator=user,
                pid_provider_xml=registered,
                pid_type=pid_type,
                pid_in_xml=pid_in_xml,
                version=version,
            )

        registered, previous, current = create("V3-CURRENT", "V2-CURRENT")
        other, _, other_current = create("V3-OTHER", "V2-OTHER")
        # PIDs da versão então atual (previous)
        other_pid(registered, "pid_v3", "V3-PREVIOUS", previous)
        other_pid(registered, "pid_v2", "V2-PREVIOUS", previous)
        # repetido
        other_pid(registered, "pid_v3", "V3-PREVIOUS", previous)
        # aop_pid é pid v2 que o documento tinha como ahead of print
        other_pid(registered, "aop_pid", "AOP-PREVIOUS", previous)
        # sem versão
        other_pid(registered, "pid_v3", "V3-WITHOUT-VERSION", None)
        # versão de outro documento (ex.: fix_duplicated_pkg_name)
        other_pid(registered, "pid_v3", "V3-OTHER", other_current)
        # versão que já tem o pid (versão atual)
        other_pid(registered, "pid_v3", "V3-OF-CURRENT", current)
        # sem documento
        other_pid(None, "pid_v3", "V3-WITHOUT-DOCUMENT", previous)

        self.ids = {
            "registered": registered.pk,
            "previous": previous.pk,
            "current": current.pk,
            "other": other.pk,
            "other_current": other_current.pk,
        }

        self.apps = migrate(MIGRATE_TO)

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def version(self, name):
        XMLVersion = self.apps.get_model("pid_provider", "XMLVersion")
        return XMLVersion.objects.get(pk=self.ids[name])

    def test_migration(self):
        for check in (
            self.check_current_version_has_the_document_pids,
            self.check_previous_version_has_the_changed_pids,
            self.check_pids_without_available_version_are_registered_without_file,
            self.check_changed_pids_locate_the_document,
            self.check_other_pid_without_document_is_ignored,
        ):
            with self.subTest(check.__name__):
                check()

    def check_current_version_has_the_document_pids(self):
        current = self.version("current")
        self.assertEqual((current.pid_v3, current.pid_v2), ("V3-CURRENT", "V2-CURRENT"))
        other_current = self.version("other_current")
        self.assertEqual(
            (other_current.pid_v3, other_current.pid_v2), ("V3-OTHER", "V2-OTHER")
        )

    def check_previous_version_has_the_changed_pids(self):
        previous = self.version("previous")
        self.assertEqual(
            (previous.pid_v3, previous.pid_v2), ("V3-PREVIOUS", "V2-PREVIOUS")
        )

    def check_pids_without_available_version_are_registered_without_file(self):
        XMLVersion = self.apps.get_model("pid_provider", "XMLVersion")
        records = XMLVersion.objects.filter(
            pid_provider_xml_id=self.ids["registered"], finger_print__isnull=True
        )
        self.assertCountEqual(
            [(item.pid_v3, item.pid_v2) for item in records],
            [
                (None, "AOP-PREVIOUS"),
                ("V3-WITHOUT-VERSION", None),
                ("V3-OTHER", None),
                ("V3-OF-CURRENT", None),
            ],
        )
        for item in records:
            self.assertFalse(item.file)
            self.assertIsNone(item.collection_id)

    def check_changed_pids_locate_the_document(self):
        PidProviderXML = self.apps.get_model("pid_provider", "PidProviderXML")
        for params in (
            {"xmlversion__pid_v3": "V3-PREVIOUS"},
            {"xmlversion__pid_v3": "V3-WITHOUT-VERSION"},
            {"xmlversion__pid_v3": "V3-OF-CURRENT"},
            {"xmlversion__pid_v2": "V2-PREVIOUS"},
            {"xmlversion__pid_v2": "AOP-PREVIOUS"},
        ):
            with self.subTest(**params):
                self.assertEqual(
                    list(
                        PidProviderXML.objects.filter(**params)
                        .distinct()
                        .values_list("pk", flat=True)
                    ),
                    [self.ids["registered"]],
                )
        # pid v3 do documento duplicado localiza os dois documentos
        self.assertCountEqual(
            PidProviderXML.objects.filter(xmlversion__pid_v3="V3-OTHER")
            .distinct()
            .values_list("pk", flat=True),
            [self.ids["registered"], self.ids["other"]],
        )

    def check_other_pid_without_document_is_ignored(self):
        XMLVersion = self.apps.get_model("pid_provider", "XMLVersion")
        self.assertFalse(
            XMLVersion.objects.filter(pid_v3="V3-WITHOUT-DOCUMENT").exists()
        )
