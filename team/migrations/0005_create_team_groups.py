from django.db import migrations

CANONICAL_NAMES = [
    "COLLECTION_TEAM_ADMIN",
    "COLLECTION_TEAM_MEMBER",
    "JOURNAL_TEAM_ADMIN",
    "JOURNAL_TEAM_MEMBER",
    "COMPANY_TEAM_ADMIN",
    "COMPANY_MEMBER",
]


def create_team_groups(apps, _schema_editor):
    Group = apps.get_model("auth", "Group")

    for name in CANONICAL_NAMES:
        Group.objects.get_or_create(name=name)

    try:
        legacy = Group.objects.get(name="COMPANY_TEAM_MEMBER")
    except Group.DoesNotExist:
        return

    canonical = Group.objects.get(name="COMPANY_MEMBER")

    for user in legacy.user_set.all():
        user.groups.add(canonical)

    for perm in legacy.permissions.all():
        canonical.permissions.add(perm)

    legacy.delete()


def remove_team_groups(apps, _schema_editor):
    Group = apps.get_model("auth", "Group")

    Group.objects.filter(name__in=CANONICAL_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [
        (
            "team",
            "0004_rename_team_collec_collect_idx_team_collec_collect_0ee96e_idx_and_more",
        ),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_team_groups, remove_team_groups),
    ]
