# Generated by Django 5.0.3 on 2025-05-29 14:55

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("journal", "0011_alter_journal_contact_address_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="JournalTOC",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("journal.journal", models.Model),
        ),
        migrations.AlterField(
            model_name="journal",
            name="official_journal",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="journal.officialjournal",
            ),
        ),
        migrations.AlterField(
            model_name="journalsection",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="j_sections",
                to="journal.journaltoc",
            ),
        ),
    ]
