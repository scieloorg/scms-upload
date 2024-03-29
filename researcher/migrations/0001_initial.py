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
            name="Researcher",
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
                    "given_names",
                    models.CharField(max_length=128, verbose_name="Given names"),
                ),
                (
                    "last_name",
                    models.CharField(max_length=128, verbose_name="Last name"),
                ),
                (
                    "suffix",
                    models.CharField(
                        blank=True, max_length=128, null=True, verbose_name="Suffix"
                    ),
                ),
                (
                    "orcid",
                    models.TextField(blank=True, null=True, verbose_name="ORCID"),
                ),
                (
                    "lattes",
                    models.TextField(blank=True, null=True, verbose_name="Lattes"),
                ),
                (
                    "gender",
                    models.CharField(
                        choices=[("F", "Mujer"), ("M", "Hombre")],
                        max_length=1,
                        verbose_name="Gender",
                    ),
                ),
                (
                    "gender_identification_status",
                    models.CharField(
                        choices=[
                            ("DECLARED", "Declarado por el investigador"),
                            (
                                "AUTOMATIC",
                                "Identificado automáticamente por programa de computador",
                            ),
                            ("MANUAL", "Identificado por algun usuario"),
                        ],
                        max_length=255,
                        verbose_name="Gender identification status",
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
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="FieldEmail",
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
                    "sort_order",
                    models.IntegerField(blank=True, editable=False, null=True),
                ),
                (
                    "email",
                    models.EmailField(
                        blank=True, max_length=128, null=True, verbose_name="Email"
                    ),
                ),
                (
                    "page",
                    modelcluster.fields.ParentalKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="page_email",
                        to="researcher.researcher",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order"],
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="FieldAffiliation",
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
                        related_name="affiliation",
                        to="researcher.researcher",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order"],
                "abstract": False,
            },
            bases=("institution.institutionhistory", models.Model),
        ),
    ]
