from django.db import migrations
from django.db.models import F, OuterRef, Subquery


def fix_sps_pkg_name(apps, schema_editor):
    """
    CollectionPidV2.sps_pkg_name foi preenchido com o pid v3 (nome do
    arquivo de XMLVersion) em vez do nome do pacote. Corrige com o nome
    efetivo do pacote (SPSPkg.sps_pkg_name). Os registros sem pacote ficam
    a cargo de task_complete_collection_pid_v2_sps_pkg_name.
    """
    CollectionPidV2 = apps.get_model("pid_provider", "CollectionPidV2")
    SPSPkg = apps.get_model("package", "SPSPkg")

    sps_pkg_name = SPSPkg.objects.filter(
        collection_pid_v2_id=OuterRef("pk"), sps_pkg_name__isnull=False
    ).exclude(sps_pkg_name="").values("sps_pkg_name")[:1]

    (
        CollectionPidV2.objects.filter(sps_pkg__isnull=False)
        .annotate(pkg_name=Subquery(sps_pkg_name))
        .filter(pkg_name__isnull=False)
        .exclude(sps_pkg_name=F("pkg_name"))
        .update(sps_pkg_name=Subquery(sps_pkg_name))
    )


class Migration(migrations.Migration):

    dependencies = [
        ("pid_provider", "0019_collectionpidv2_sps_pkg_name"),
        ("package", "0010_remove_spspkg_package_sps_pid_v3_74c613_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(fix_sps_pkg_name, migrations.RunPython.noop),
    ]
