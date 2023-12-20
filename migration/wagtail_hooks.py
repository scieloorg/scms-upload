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
from htmlxml.models import HTMLXML
from migration.models import (
    ClassicWebsiteConfiguration,
    MigratedArticle,
    MigratedData,
    MigratedFile,
    MigratedIssue,
    MigratedJournal,
)

# class MigrationFailureAdmin(ModelAdmin):
#     model = MigrationFailure
#     inspect_view_enabled = True
#     menu_label = _("Migration Failures")
#     menu_icon = "folder"
#     menu_order = 200
#     add_to_settings_menu = False
#     exclude_from_explorer = False

#     list_display = (
#         "action_name",
#         "migrated_item_name",
#         "migrated_item_id",
#         "message",
#         "updated",
#     )
#     list_filter = (
#         "action_name",
#         "migrated_item_name",
#         "exception_type",
#     )
#     search_fields = (
#         "action_name",
#         "migrated_item_id",
#         "message",
#         "exception_msg",
#     )
#     inspect_view_fields = (
#         "action_name",
#         "migrated_item_name",
#         "migrated_item_id",
#         "exception_type",
#         "exception_msg",
#         "updated",
#     )


class CoreCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class ClassicWebsiteConfigurationModelAdmin(ModelAdmin):
    model = ClassicWebsiteConfiguration
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


class MigratedDataModelAdmin(ModelAdmin):
    model = MigratedData
    menu_label = _("Migrated Data")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "collection",
        "pid",
        "content_type",
        "migration_status",
        "isis_updated_date",
        "updated",
        "created",
    )
    list_filter = (
        "migration_status",
        "content_type",
    )
    search_fields = ("pid", "collection__acron", "collection__name")
    inspect_view_fields = (
        "updated",
        "created",
        "content_type",
        "migration_status",
        "isis_created_date",
        "isis_updated_date",
        "data",
    )


class MigratedArticleModelAdmin(ModelAdmin):
    model = MigratedArticle
    menu_label = _("Migrated Article")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "collection",
        "pid",
        "migration_status",
        "isis_updated_date",
        "updated",
        "created",
    )
    list_filter = ("migration_status",)
    search_fields = ("pid", "collection__acron", "collection__name")
    inspect_view_fields = (
        "updated",
        "created",
        "migration_status",
        "isis_created_date",
        "isis_updated_date",
        "data",
    )


class MigratedJournalModelAdmin(ModelAdmin):
    model = MigratedJournal
    menu_label = _("Migrated Journal")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "collection",
        "pid",
        "migration_status",
        "isis_updated_date",
        "updated",
        "created",
    )
    list_filter = ("migration_status",)
    search_fields = ("pid", "collection__acron", "collection__name")
    inspect_view_fields = (
        "updated",
        "created",
        "migration_status",
        "isis_created_date",
        "isis_updated_date",
        "data",
    )


class MigratedIssueModelAdmin(ModelAdmin):
    model = MigratedIssue
    menu_label = _("Migrated Issue")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "collection",
        "pid",
        "migration_status",
        "isis_updated_date",
        "updated",
        "created",
    )
    list_filter = ("migration_status",)
    search_fields = ("pid", "collection__acron", "collection__name")
    inspect_view_fields = (
        "updated",
        "created",
        "migration_status",
        "isis_created_date",
        "isis_updated_date",
        "data",
    )


class MigratedFileModelAdmin(ModelAdmin):
    model = MigratedFile
    menu_label = _("Migrated files")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "collection",
        "original_path",
        "created",
        "updated",
    )
    search_fields = ("original_path",)
    inspect_view_fields = (
        "collection",
        "original_path",
        "file",
        "created",
        "updated",
    )


# class BodyAndBackFileModelAdmin(ModelAdmin):
#     model = article_BodyAndBackFile
#     menu_label = _("Body and back")
#     menu_icon = "doc-full"
#     menu_order = 300
#     add_to_settings_menu = False
#     exclude_from_explorer = True
#     inspect_view_enabled = True

#     list_per_page = 10
#     create_view_class = CoreCreateView

#     list_display = (
#         "migrated_document_html",
#         "pkg_name",
#         "version",
#         "created",
#         "updated",
#     )
#     list_filter = ("version",)
#     search_fields = (
#         "collection__acron",
#         "collection__name",
#         "migrated_document_html__migrated_issue__issue_proc__journal_proc__acron",
#         "migrated_document_html__migrated_issue__issue_proc__issue__publication_year",
#         "migrated_document_html__migrated_issue__issue_proc__issue_folder",
#         "pkg_name",
#     )
#     inspect_view_fields = (
#         "collection",
#         "migrated_document_html",
#         "pkg_name",
#         "version",
#         "file",
#     )


class HTMLXMLModelAdmin(ModelAdmin):
    model = HTMLXML
    menu_label = _("XML from HTML")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = True
    inspect_view_enabled = True

    list_per_page = 10
    create_view_class = CoreCreateView

    list_display = (
        "article_proc",
        "html2xml_status",
        "quality",
        "attention_demands",
        "html_translation_langs",
        "pdf_langs",
        "n_paragraphs",
        "n_references",
        "created_updated",
    )
    list_filter = (
        "html_img_total",
        "html_table_total",
        "empty_body",
        "attention_demands",
        "article_type",
        "html2xml_status",
        "quality",
        "html_translation_langs",
        "pdf_langs",
    )
    search_fields = (
        "article_proc__migrated_data__pid",
        "article_proc__pkg_name",
        "html2xml_status",
        "article_type",
    )


class MigrationModelAdmin(ModelAdminGroup):
    menu_icon = "folder"
    menu_label = _("Migration")
    menu_order = get_menu_order("migration")

    items = (
        ClassicWebsiteConfigurationModelAdmin,
        # MigrationFailureAdmin,
        MigratedDataModelAdmin,
        MigratedJournalModelAdmin,
        MigratedIssueModelAdmin,
        MigratedArticleModelAdmin,
        MigratedFileModelAdmin,
        HTMLXMLModelAdmin,
    )
    menu_order = get_menu_order("migration")


modeladmin_register(MigrationModelAdmin)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("migration/", include("migration.urls", namespace="migration")),
    ]
