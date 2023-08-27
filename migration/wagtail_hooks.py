from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext as _
from wagtail import hooks
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.contrib.modeladmin.views import CreateView

from config.menu import get_menu_order

from . import models


class MigrationFailureAdmin(ModelAdmin):
    model = models.MigrationFailure
    inspect_view_enabled = True
    menu_label = _("Migration Failures")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "action_name",
        "migrated_item_name",
        "migrated_item_id",
        "message",
        "updated",
    )
    list_filter = (
        "action_name",
        "migrated_item_name",
        "exception_type",
    )
    search_fields = (
        "action_name",
        "migrated_item_id",
        "message",
        "exception_msg",
    )
    inspect_view_fields = (
        "action_name",
        "migrated_item_name",
        "migrated_item_id",
        "exception_type",
        "exception_msg",
        "updated",
    )


class CoreCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class ClassicWebsiteConfigurationModelAdmin(ModelAdmin):
    model = models.ClassicWebsiteConfiguration
    menu_label = _("Classic Website Configuration")
    menu_icon = "doc-full"
    menu_order = 100
    add_to_settings_menu = False
    exclude_from_explorer = False
    inspect_view_enabled = False

    create_view_class = CoreCreateView

    list_display = (
        "collection",
        "created",
        "updated",
        "updated_by",
    )
    list_filter = ("collection__acron",)
    search_fields = ("collection__acron",)


class MigratedJournalModelAdmin(ModelAdmin):
    model = models.MigratedJournal
    menu_label = _("Journal Migration")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "scielo_journal",
        "status",
        "isis_updated_date",
    )
    list_filter = ("status",)
    search_fields = ("scielo_journal__acron",)
    inspect_view_fields = (
        "scielo_journal",
        "status",
        "isis_updated_date",
        "data",
    )


class MigratedIssueModelAdmin(ModelAdmin):
    model = models.MigratedIssue
    menu_label = _("Issue Migration")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "scielo_issue",
        "status",
        "isis_updated_date",
    )
    list_filter = ("status",)
    search_fields = (
        "migrated_journal__scielo_journal__title",
        "migrated_journal__scielo_journal__acron",
        "scielo_issue__official_issue__publication_date__year",
        "scielo_issue__issue_folder",
    )
    inspect_view_fields = (
        "scielo_issue",
        "status",
        "isis_updated_date",
        "data",
    )


class MigratedDocumentModelAdmin(ModelAdmin):
    model = models.MigratedDocument
    menu_label = _("Document Migration")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "pkg_name",
        "sps_pkg_name",
        "pid",
        "status",
        "isis_updated_date",
    )
    list_filter = ("status",)
    search_fields = (
        "migrated_issue__migrated_journal__scielo_journal__acron",
        "migrated_issue__scielo_issue__official_issue__publication_year",
        "migrated_issue__scielo_issue__issue_folder",
    )
    inspect_view_fields = (
        "migrated_issue",
        "pkg_name",
        "sps_pkg_name",
        "xml",
        "status",
        "pid",
        "isis_updated_date",
        "data",
    )


class MigratedFileModelAdmin(ModelAdmin):
    model = models.MigratedFile
    menu_label = _("Migrated file")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "category",
        "original_href",
        "migrated_issue",
        "lang",
        "part",
        "created",
        "updated",
    )
    list_filter = ("category",)
    search_fields = (
        "category",
        "migrated_issue__scielo_issue__official_issue__publication_year",
        "pkg_name",
        "sps_pkg_name",
        "lang",
        "part",
        "original_href",
    )
    inspect_view_fields = (
        "category",
        "migrated_issue",
        "pkg_name",
        "sps_pkg_name",
        "lang",
        "part",
        "file",
    )


class BodyAndBackFileModelAdmin(ModelAdmin):
    model = models.BodyAndBackFile
    menu_label = _("HTML 2 XML File")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "migrated_document",
        "version",
        "created",
        "updated",
    )
    list_filter = ("version",)
    search_fields = (
        "migrated_document__migrated_issue__migrated_journal__scielo_journal__acron",
        "migrated_document__migrated_issue__scielo_issue__official_issue__publication_year",
        "migrated_document__migrated_issue__scielo_issue__issue_folder",
    )
    inspect_view_fields = (
        "migrated_document",
        "version",
        "file",
    )


class GeneratedXMLFileModelAdmin(ModelAdmin):
    model = models.GeneratedXMLFile
    menu_label = _("Generated XML File")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "migrated_document",
        "status",
        "created",
        "updated",
    )
    list_filter = ("status",)
    search_fields = (
        "migrated_document__migrated_issue__migrated_journal__scielo_journal__acron",
        "migrated_document__migrated_issue__scielo_issue__official_issue__publication_year",
        "migrated_document__migrated_issue__scielo_issue__issue_folder",
    )
    inspect_view_fields = (
        "migrated_document",
        "status",
        "file",
    )


class MigrationModelAdmin(ModelAdminGroup):
    menu_icon = "folder"
    menu_label = "Migration"
    items = (
        ClassicWebsiteConfigurationModelAdmin,
        MigrationFailureAdmin,
        MigratedJournalModelAdmin,
        MigratedIssueModelAdmin,
        MigratedFileModelAdmin,
        MigratedDocumentModelAdmin,
        BodyAndBackFileModelAdmin,
        GeneratedXMLFileModelAdmin,
    )
    menu_order = get_menu_order("migration")


modeladmin_register(MigrationModelAdmin)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("migration/", include("migration.urls", namespace="migration")),
    ]
