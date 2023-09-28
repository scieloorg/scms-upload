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
    menu_label = _("Journals")
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
    menu_label = _("Issues")
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
    menu_label = _("Articles")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "migrated_issue",
        "pkg_name",
        "sps_pkg",
        "pid",
        "status",
        "xml_status",
        "isis_updated_date",
    )
    list_filter = (
        "status",
        "xml_status",
        "migrated_issue__scielo_issue__official_issue__publication_year",
    )
    search_fields = (
        "migrated_issue__migrated_journal__scielo_journal__acron",
        "migrated_issue__scielo_issue__official_issue__publication_year",
        "migrated_issue__scielo_issue__issue_folder",
    )
    inspect_view_fields = (
        "collection",
        "pid",
        "migrated_issue",
        "pkg_name",
        "sps_pkg_name",
        "status",
        "xml_status",
        "isis_updated_date",
        "data",
        "file",
    )


class MigratedFileModelAdmin(ModelAdmin):
    model = models.MigratedFile
    menu_label = _("Migrated files")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "migrated_issue",
        "created",
        "updated",
    )
    search_fields = ("migrated_issue__scielo_issue__official_issue__publication_year",)
    inspect_view_fields = (
        "migrated_issue",
        "file",
    )


class BodyAndBackFileModelAdmin(ModelAdmin):
    model = models.BodyAndBackFile
    menu_label = _("XML with body and back")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "migrated_issue",
        "pkg_name",
        "version",
        "created",
        "updated",
    )
    list_filter = ("version",)
    search_fields = (
        "collection__acron",
        "collection__name",
        "migrated_issue",
        "pkg_name",
    )
    inspect_view_fields = (
        "collection",
        "migrated_issue",
        "pkg_name",
        "version",
        "file",
    )


class MigratedDocumentHTMLModelAdmin(ModelAdmin):
    model = models.MigratedDocumentHTML
    menu_label = _("Migrated document (html)")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "migrated_issue",
        "pkg_name",
        "sps_pkg",
        "pid",
        "status",
        "xml_status",
        "isis_updated_date",
    )
    list_filter = (
        "status",
        "xml_status",
        "migrated_issue__scielo_issue__official_issue__publication_year",
    )
    search_fields = (
        "migrated_issue__migrated_journal__scielo_journal__acron",
        "migrated_issue__scielo_issue__official_issue__publication_year",
        "migrated_issue__scielo_issue__issue_folder",
    )
    inspect_view_fields = (
        "collection",
        "pid",
        "migrated_issue",
        "pkg_name",
        "sps_pkg_name",
        "status",
        "xml_status",
        "isis_updated_date",
        "data",
        "file",
    )


class Html2xmlReportModelAdmin(ModelAdmin):
    model = models.Html2xmlReport
    menu_label = _("HTML 2 XML report")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "xml",
        "attention_demands",
        "img_src_total",
        "table_total",
        "fig_total",
        "table_wrap_total",
        "text_lang_total",
        "updated",
    )
    list_filter = (
        "empty_body",
        "article_type",
        "attention_demands",
    )
    search_fields = (
        "xml__collection__acron",
        "xml__pid",
        "xml__migrated_issue",
        "xml__pkg_name",
    )


class MigrationModelAdmin(ModelAdminGroup):
    menu_icon = "folder"
    menu_label = "Migration"
    menu_order = get_menu_order("migration")

    items = (
        ClassicWebsiteConfigurationModelAdmin,
        MigrationFailureAdmin,
        MigratedJournalModelAdmin,
        MigratedIssueModelAdmin,
        MigratedFileModelAdmin,
        MigratedDocumentModelAdmin,
        MigratedDocumentHTMLModelAdmin,
        Html2xmlReportModelAdmin,
        BodyAndBackFileModelAdmin,
    )
    menu_order = get_menu_order("migration")


modeladmin_register(MigrationModelAdmin)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("migration/", include("migration.urls", namespace="migration")),
    ]
