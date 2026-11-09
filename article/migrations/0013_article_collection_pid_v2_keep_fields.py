import django.db.models.deletion
from django.db import migrations, models

from core.utils.migration_operations import (
    AddConstraintIfNotExists,
    AddFieldIfNotExists,
    AddIndexIfNotExists,
    AlterFieldRemoveUniqueIfExists,
    ensure_fields_and_indexes,
)


def fill_fields_from_collection_pid_v2(apps, schema_editor):
    """
    Bancos que aplicaram a versão anterior desta migração (somente
    desenvolvimento) tiveram pp_xml, sps_pkg e pid_v2 removidos e recriados
    vazios: preenche-os a partir de collection_pid_v2.

    Nos demais bancos, collection_pid_v2 acabou de ser criado (vazio): não há
    o que preencher.
    """
    Article = apps.get_model("article", "Article")
    SPSPkg = apps.get_model("package", "SPSPkg")
    for article in (
        Article.objects.filter(collection_pid_v2__isnull=False)
        .filter(
            models.Q(pp_xml__isnull=True)
            | models.Q(sps_pkg__isnull=True)
            | models.Q(pid_v2__isnull=True)
        )
        .select_related("collection_pid_v2")
        .iterator()
    ):
        collection_pid_v2 = article.collection_pid_v2
        sps_pkg_id = (
            article.sps_pkg_id
            or SPSPkg.objects.filter(collection_pid_v2_id=collection_pid_v2.id)
            .values_list("id", flat=True)
            .first()
        )
        Article.objects.filter(id=article.id).update(
            pp_xml_id=article.pp_xml_id or collection_pid_v2.pid_provider_xml_id,
            pid_v2=article.pid_v2 or collection_pid_v2.pid_v2,
            sps_pkg_id=sps_pkg_id,
        )
    if schema_editor.connection.vendor == "postgresql":
        # dispara as verificações de FK adiadas antes das próximas alterações
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):
    """
    Vínculo do artigo com o documento na coleção (CollectionPidV2) e um
    Article por coleção (pid_v3 deixa de ser único).

    Somente altera o esquema: sps_pkg, pp_xml e pid_v2 são mantidos e os
    artigos existentes são vinculados ao serem obtidos ou pela tarefa
    article.tasks.task_complete_collection_pid_v2.

    As operações são idempotentes no banco, para funcionar também nos bancos
    que aplicaram a versão anterior desta migração
    (0013_remove_article_pid_v2_remove_article_pp_xml_and_more, que removia
    pid_v2, pp_xml e sps_pkg): recria o que falta e não recria o que existe.
    """

    dependencies = [
        ("article", "0012_article_data_availability_status"),
        ("package", "0010_spspkg_collection_pid_v2_keep_fields"),
        ("pid_provider", "0018_collectionpidv2"),
    ]

    operations = [
        ensure_fields_and_indexes(
            "article", "Article", field_names=["pp_xml", "sps_pkg", "pid_v2"]
        ),
        AddFieldIfNotExists(
            model_name="article",
            name="collection_pid_v2",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="article",
                to="pid_provider.collectionpidv2",
            ),
        ),
        AlterFieldRemoveUniqueIfExists(
            model_name="article",
            name="pid_v3",
            field=models.CharField(
                blank=True, max_length=23, null=True, verbose_name="PID v3"
            ),
        ),
        AddIndexIfNotExists(
            model_name="article",
            index=models.Index(fields=["pid_v3"], name="article_art_pid_v3_2370cc_idx"),
        ),
        AddIndexIfNotExists(
            model_name="article",
            index=models.Index(fields=["pid_v2"], name="article_art_pid_v2_fa7897_idx"),
        ),
        AddConstraintIfNotExists(
            model_name="article",
            constraint=models.UniqueConstraint(
                condition=models.Q(("collection_pid_v2__isnull", True)),
                fields=("pid_v3",),
                name="article_unique_pid_v3_without_collection",
            ),
        ),
        migrations.RunPython(
            fill_fields_from_collection_pid_v2, migrations.RunPython.noop
        ),
    ]
