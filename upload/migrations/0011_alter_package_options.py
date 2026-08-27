from django.db import migrations


def _rename_permission(
    apps,
    schema_editor,
    old_codename,
    new_codename,
    new_name,
):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    database = schema_editor.connection.alias

    content_type = (
        ContentType.objects.using(database)
        .filter(app_label="upload", model="package")
        .first()
    )
    if not content_type:
        return

    old_permission = Permission.objects.using(database).filter(
        content_type=content_type,
        codename=old_codename,
    ).first()
    new_permission, _ = Permission.objects.using(database).get_or_create(
        content_type=content_type,
        codename=new_codename,
        defaults={"name": new_name},
    )
    if new_permission.name != new_name:
        new_permission.name = new_name
        new_permission.save(update_fields=["name"])

    if not old_permission:
        return

    group_ids = old_permission.group_set.using(database).values_list("pk", flat=True)
    group_permissions = old_permission.group_set.through
    group_permissions.objects.using(database).bulk_create(
        [
            group_permissions(group_id=group_id, permission_id=new_permission.pk)
            for group_id in group_ids
        ],
        ignore_conflicts=True,
    )

    user_ids = old_permission.user_set.using(database).values_list("pk", flat=True)
    user_permissions = old_permission.user_set.through
    user_permissions.objects.using(database).bulk_create(
        [
            user_permissions(user_id=user_id, permission_id=new_permission.pk)
            for user_id in user_ids
        ],
        ignore_conflicts=True,
    )

    old_permission.delete()


def rename_permission(apps, schema_editor):
    _rename_permission(
        apps,
        schema_editor,
        "access_all_packages",
        "access_packages",
        "Can access packages from all users within authorized scope",
    )


def restore_permission(apps, schema_editor):
    _rename_permission(
        apps,
        schema_editor,
        "access_packages",
        "access_all_packages",
        "Can access all packages from all users",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("upload", "0010_alter_package_category_alter_package_status"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="package",
            options={
                "permissions": (
                    ("finish_deposit", "Can finish deposit"),
                    (
                        "access_packages",
                        "Can access packages from all users within authorized scope",
                    ),
                    ("assign_package", "Can assign package"),
                    ("publish_package", "Can publish package"),
                    ("republish_package", "Can republish package"),
                ),
                "verbose_name": "Package admin",
                "verbose_name_plural": "Package admin",
            },
        ),
        migrations.RunPython(rename_permission, restore_permission),
    ]
