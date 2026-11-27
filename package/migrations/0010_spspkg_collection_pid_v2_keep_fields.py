import django.db.models.deletion
from django.db import migrations, models

from core.utils.migration_operations import (
    AddFieldIfNotExists,
    AddIndexIfNotExists,
    ensure_fields_and_indexes,
)


def fill_fields_from_collection_pid_v2(apps, schema_editor):
    """
    Bancos que aplicaram a versão anterior desta migração (somente
    desenvolvimento) tiveram ppx, pid_v3 e pid_v2 removidos e recriados
    vazios: preenche-os a partir de collection_pid_v2.

    Nos demais bancos, collection_pid_v2 acabou de ser criado (vazio): não há
    o que preencher.
    """
    SPSPkg = apps.get_model("package", "SPSPkg")
    for sps_pkg in (
        SPSPkg.objects.filter(collection_pid_v2__isnull=False, ppx__isnull=True)
        .select_related("collection_pid_v2__pid_provider_xml")
        .iterator()
    ):
        collection_pid_v2 = sps_pkg.collection_pid_v2
        SPSPkg.objects.filter(id=sps_pkg.id).update(
            ppx_id=collection_pid_v2.pid_provider_xml_id,
            pid_v3=sps_pkg.pid_v3 or collection_pid_v2.pid_provider_xml.v3,
            pid_v2=sps_pkg.pid_v2 or collection_pid_v2.pid_v2,
        )
    if schema_editor.connection.vendor == "postgresql":
        # dispara as verificações de FK adiadas antes das próximas alterações
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):
    """
    Vínculo do pacote com o documento na coleção (CollectionPidV2).

    Somente adiciona o campo (nullable): ppx, pid_v3 e pid_v2 são mantidos e
    os pacotes existentes são vinculados ao serem obtidos ou pela tarefa
    article.tasks.task_complete_collection_pid_v2.

    As operações são idempotentes no banco, para funcionar também nos bancos
    que aplicaram a versão anterior desta migração
    (0010_remove_spspkg_package_sps_pid_v3_74c613_idx_and_more, que removia
    ppx, pid_v3 e pid_v2): recria o que falta e não recria o que existe.
    """

    dependencies = [
        ("package", "0009_spspkg_ppx"),
        ("pid_provider", "0018_collectionpidv2"),
    ]

    operations = [
        ensure_fields_and_indexes(
            "package",
            "SPSPkg",
            field_names=["pid_v3", "pid_v2", "ppx"],
            index_names=["package_sps_pid_v3_74c613_idx"],
        ),
        AddFieldIfNotExists(
            model_name="spspkg",
            name="collection_pid_v2",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sps_pkg",
                to="pid_provider.collectionpidv2",
            ),
        ),
        AddIndexIfNotExists(
            model_name="spspkg",
            index=models.Index(fields=["pid_v2"], name="package_sps_pid_v2_129894_idx"),
        ),
        migrations.RunPython(
            fill_fields_from_collection_pid_v2, migrations.RunPython.noop
        ),
    ]
