from django.db import models
from django.utils.translation import gettext_lazy as _

from collection.models import (
    ClassicWebsiteConfiguration,
    FilesStorageConfiguration,
    NewWebSiteConfiguration,
    SciELODocument,
    SciELOIssue,
    SciELOJournal,
)
from core.forms import CoreAdminModelForm
from core.models import CommonControlField

from . import choices


class MigrationConfiguration(CommonControlField):
    classic_website_config = models.ForeignKey(
        ClassicWebsiteConfiguration, on_delete=models.CASCADE
    )
    new_website_config = models.ForeignKey(
        NewWebSiteConfiguration, on_delete=models.CASCADE
    )
    files_storage_config = models.ForeignKey(
        FilesStorageConfiguration, on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.classic_website_config}"

    class Meta:
        indexes = [
            models.Index(fields=["classic_website_config"]),
        ]

    base_form_class = CoreAdminModelForm


class MigratedData(CommonControlField):
    # datas no registro da base isis para identificar
    # se houve mudança nos dados durante a migração
    isis_updated_date = models.CharField(
        _("ISIS updated date"), max_length=8, null=True, blank=True
    )
    isis_created_date = models.CharField(
        _("ISIS created date"), max_length=8, null=True, blank=True
    )

    # dados migrados
    data = models.JSONField(blank=True, null=True)

    # status da migração
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=choices.MIGRATION_STATUS,
        default=choices.MS_TO_MIGRATE,
    )

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["isis_updated_date"]),
        ]


class MigrationFailure(CommonControlField):
    action_name = models.TextField(_("Action"), null=False, blank=False)
    object_name = models.TextField(_("Object"), null=False, blank=False)
    pid = models.CharField(_("Item PID"), max_length=23, null=False, blank=False)
    exception_type = models.TextField(
        _("Exception Type"),
        null=False,
        blank=False
    )
    exception_msg = models.TextField(
        _("Exception Msg"),
        null=False,
        blank=False
    )
    traceback = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["object_name"]),
            models.Index(fields=["pid"]),
            models.Index(fields=["action_name"]),
        ]


class JournalMigration(MigratedData):
    scielo_journal = models.ForeignKey(SciELOJournal, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.scielo_journal} {self.status}"

    class Meta:
        indexes = [
            models.Index(fields=["scielo_journal"]),
        ]


class IssueMigration(MigratedData):
    scielo_issue = models.ForeignKey(SciELOIssue, on_delete=models.CASCADE)
    files_status = models.CharField(
        _("Status"),
        max_length=20,
        choices=choices.MIGRATION_STATUS,
        default=choices.MS_TO_MIGRATE,
    )

    def __str__(self):
        return f"{self.scielo_issue} | data: {self.status} | files: {self.files_status}"

    class Meta:
        indexes = [
            models.Index(fields=["scielo_issue"]),
        ]


class DocumentMigration(MigratedData):
    scielo_document = models.ForeignKey(SciELODocument, on_delete=models.CASCADE)
    files_status = models.CharField(
        _("Status"),
        max_length=20,
        choices=choices.MIGRATION_STATUS,
        default=choices.MS_TO_MIGRATE,
    )

    def __str__(self):
        return (
            f"{self.scielo_document} | data: {self.status} | files: {self.files_status}"
        )

    class Meta:
        indexes = [
            models.Index(fields=["scielo_document"]),
        ]
