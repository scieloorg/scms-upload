# Generated manually for journal membership and company contracts

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("journal", "0014_alter_journal_title_alter_officialjournal_title"),
        ("company", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="JournalMember",
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
                    "journal",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="journal_members",
                        to="journal.journal",
                        verbose_name="Journal",
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
                        related_name="journal_memberships",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="User",
                    ),
                ),
            ],
            options={
                "verbose_name": "Journal Member",
                "verbose_name_plural": "Journal Members",
                "unique_together": {("user", "journal")},
            },
        ),
        migrations.CreateModel(
            name="JournalCompanyContract",
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
                    "initial_date",
                    models.DateField(
                        blank=True, null=True, verbose_name="Contract Start Date"
                    ),
                ),
                (
                    "final_date",
                    models.DateField(
                        blank=True, 
                        null=True, 
                        verbose_name="Contract End Date",
                        help_text="Leave blank for active contracts. Set to end contract.",
                    ),
                ),
                (
                    "notes",
                    models.TextField(blank=True, null=True, verbose_name="Notes"),
                ),
                (
                    "journal",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="company_contracts",
                        to="journal.journal",
                        verbose_name="Journal",
                    ),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="journal_contracts",
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
            ],
            options={
                "verbose_name": "Journal-Company Contract",
                "verbose_name_plural": "Journal-Company Contracts",
                "unique_together": {("journal", "company")},
            },
        ),
        migrations.AddIndex(
            model_name="journalmember",
            index=models.Index(fields=["role"], name="journal_jou_role_8d3f5a_idx"),
        ),
        migrations.AddIndex(
            model_name="journalmember",
            index=models.Index(fields=["is_active_member"], name="journal_jou_is_acti_6c2e9d_idx"),
        ),
        migrations.AddIndex(
            model_name="journalcompanycontract",
            index=models.Index(fields=["initial_date"], name="journal_jou_initial_1a4b7f_idx"),
        ),
        migrations.AddIndex(
            model_name="journalcompanycontract",
            index=models.Index(fields=["final_date"], name="journal_jou_final_d_5e9c2a_idx"),
        ),
    ]
