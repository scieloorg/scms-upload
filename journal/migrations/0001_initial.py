# Generated by Django 4.2.6 on 2024-01-23 22:35

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import modelcluster.fields


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("institution", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Journal",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    models.DateTimeField(
                        auto_now_add=True, verbose_name="Creation date"
                    ),
                ),
                (
                    "updated",
                    models.DateTimeField(
                        auto_now=True, verbose_name="Last update date"
                    ),
                ),
                (
                    "short_title",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        null=True,
                        verbose_name="Short Title",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Creator",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Publisher",
            fields=[
                (
                    "institutionhistory_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="institution.institutionhistory",
                    ),
                ),
                (
                    "sort_order",
                    models.IntegerField(blank=True, editable=False, null=True),
                ),
                (
                    "page",
                    modelcluster.fields.ParentalKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="publisher",
                        to="journal.journal",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order"],
                "abstract": False,
            },
            bases=("institution.institutionhistory", models.Model),
        ),
        migrations.CreateModel(
            name="Owner",
            fields=[
                (
                    "institutionhistory_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="institution.institutionhistory",
                    ),
                ),
                (
                    "sort_order",
                    models.IntegerField(blank=True, editable=False, null=True),
                ),
                (
                    "page",
                    modelcluster.fields.ParentalKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="owner",
                        to="journal.journal",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order"],
                "abstract": False,
            },
            bases=("institution.institutionhistory", models.Model),
        ),
        migrations.CreateModel(
            name="OfficialJournal",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    models.DateTimeField(
                        auto_now_add=True, verbose_name="Creation date"
                    ),
                ),
                (
                    "updated",
                    models.DateTimeField(
                        auto_now=True, verbose_name="Last update date"
                    ),
                ),
                (
                    "title",
                    models.TextField(
                        blank=True, null=True, verbose_name="Official Title"
                    ),
                ),
                (
                    "title_iso",
                    models.TextField(blank=True, null=True, verbose_name="ISO Title"),
                ),
                (
                    "foundation_year",
                    models.CharField(
                        blank=True,
                        max_length=4,
                        null=True,
                        verbose_name="Foundation Year",
                    ),
                ),
                (
                    "issn_print",
                    models.CharField(
                        blank=True, max_length=9, null=True, verbose_name="ISSN Print"
                    ),
                ),
                (
                    "issn_electronic",
                    models.CharField(
                        blank=True,
                        max_length=9,
                        null=True,
                        verbose_name="ISSN Eletronic",
                    ),
                ),
                (
                    "issnl",
                    models.CharField(
                        blank=True, max_length=9, null=True, verbose_name="ISSNL"
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Creator",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)s_last_mod_user",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Updater",
                    ),
                ),
            ],
            options={
                "verbose_name": "Official Journal",
                "verbose_name_plural": "Official Journals",
            },
        ),
        migrations.AddField(
            model_name="journal",
            name="official_journal",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="journal.officialjournal",
            ),
        ),
        migrations.AddField(
            model_name="journal",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="%(class)s_last_mod_user",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Updater",
            ),
        ),
        migrations.AddIndex(
            model_name="officialjournal",
            index=models.Index(
                fields=["issn_print"], name="journal_off_issn_pr_dccb39_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="officialjournal",
            index=models.Index(
                fields=["issn_electronic"], name="journal_off_issn_el_89169a_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="officialjournal",
            index=models.Index(fields=["issnl"], name="journal_off_issnl_4304c5_idx"),
        ),
    ]
