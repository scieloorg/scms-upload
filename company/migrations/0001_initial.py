# Generated manually for company app

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("location", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Company",
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
                    "name",
                    models.CharField(max_length=255, unique=True, verbose_name="Company Name"),
                ),
                (
                    "acronym",
                    models.CharField(
                        blank=True, max_length=50, null=True, verbose_name="Acronym"
                    ),
                ),
                (
                    "description",
                    models.TextField(blank=True, null=True, verbose_name="Description"),
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
                (
                    "location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="location.location",
                        verbose_name="Location",
                    ),
                ),
            ],
            options={
                "verbose_name": "Company",
                "verbose_name_plural": "Companies",
            },
        ),
        migrations.CreateModel(
            name="CompanyMember",
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
                    "role",
                    models.CharField(
                        choices=[("manager", "Manager"), ("member", "Member")],
                        default="member",
                        max_length=20,
                        verbose_name="Role",
                    ),
                ),
                (
                    "is_active_member",
                    models.BooleanField(default=True, verbose_name="Active Member"),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="company_members",
                        to="company.company",
                        verbose_name="Company",
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
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="company_memberships",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="User",
                    ),
                ),
            ],
            options={
                "verbose_name": "Company Member",
                "verbose_name_plural": "Company Members",
                "unique_together": {("user", "company")},
            },
        ),
        migrations.AddIndex(
            model_name="company",
            index=models.Index(fields=["name"], name="company_com_name_a1d5e6_idx"),
        ),
        migrations.AddIndex(
            model_name="company",
            index=models.Index(fields=["acronym"], name="company_com_acronym_8b2c3f_idx"),
        ),
        migrations.AddIndex(
            model_name="companymember",
            index=models.Index(fields=["role"], name="company_com_role_7f4a2d_idx"),
        ),
        migrations.AddIndex(
            model_name="companymember",
            index=models.Index(fields=["is_active_member"], name="company_com_is_acti_9e5c1b_idx"),
        ),
    ]
