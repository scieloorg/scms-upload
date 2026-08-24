from django.db import migrations, models


def normalize_active_members(apps, _schema_editor):
    for model_name in (
        "CollectionTeamMember",
        "CompanyTeamMember",
        "JournalTeamMember",
    ):
        model = apps.get_model("team", model_name)
        model.objects.filter(is_active_member__isnull=True).update(
            is_active_member=False
        )


class Migration(migrations.Migration):
    dependencies = [
        ("team", "0005_create_team_groups"),
    ]

    operations = [
        migrations.RunPython(normalize_active_members, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="collectionteammember",
            name="is_active_member",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="companyteammember",
            name="is_active_member",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="journalteammember",
            name="is_active_member",
            field=models.BooleanField(default=True),
        ),
    ]
