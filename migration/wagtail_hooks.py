from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail.snippets.models import register_snippet

from config.menu import get_menu_order
from migration.models import (
    ClassicWebsiteConfiguration,
    IdFileRecord,
    MigratedArticle,
    MigratedData,
    MigratedFile,
    MigratedIssue,
    MigratedJournal,
)


class ClassicWebsiteConfigurationViewSet(SnippetViewSet):
    model = ClassicWebsiteConfiguration
    menu_label = _("Classic Website Configuration")
    menu_icon = "doc-full"
    menu_order = 100
    add_to_settings_menu = False
    
    list_display = [
        "collection",
        "created",
        "updated",
        "updated_by",
    ]
    list_filter = [
        "collection",
    ]
    search_fields = ["collection__acron", "collection__name"]


class MigratedDataViewSet(SnippetViewSet):
    model = MigratedData
    menu_label = _("Migrated Data")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    inspect_view_enabled = True
    
    list_per_page = 10
    list_display = [
        "pid",
        "collection",
        "content_type",
        "migration_status",
        "isis_updated_date",
        "updated",
        "created",
    ]
    list_filter = [
        "migration_status",
        "content_type",
        "collection",
    ]
    search_fields = ["pid", "collection__acron", "collection__name"]
    inspect_view_fields = [
        "updated",
        "created",
        "content_type",
        "migration_status",
        "isis_created_date",
        "isis_updated_date",
        "data",
    ]


class MigratedArticleViewSet(SnippetViewSet):
    model = MigratedArticle
    menu_label = _("Migrated Article")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    inspect_view_enabled = True
    
    list_per_page = 10
    list_display = [
        "pid",
        "collection",
        "migration_status",
        "file_type",
        "isis_updated_date",
        "updated",
        "created",
    ]
    list_filter = [
        "file_type",
        "migration_status",
        "collection",
    ]
    search_fields = ["pid", "collection__acron", "collection__name"]
    inspect_view_fields = [
        "updated",
        "created",
        "migration_status",
        "isis_created_date",
        "isis_updated_date",
        "data",
    ]


class MigratedJournalViewSet(SnippetViewSet):
    model = MigratedJournal
    menu_label = _("Migrated Journal")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    inspect_view_enabled = True
    
    list_per_page = 10
    list_display = [
        "pid",
        "collection",
        "migration_status",
        "isis_updated_date",
        "updated",
        "created",
    ]
    list_filter = [
        "migration_status",
        "collection",
    ]
    search_fields = ["pid", "collection__acron", "collection__name"]
    inspect_view_fields = [
        "updated",
        "created",
        "migration_status",
        "isis_created_date",
        "isis_updated_date",
        "data",
    ]


class MigratedIssueViewSet(SnippetViewSet):
    model = MigratedIssue
    menu_label = _("Migrated Issue")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    inspect_view_enabled = True
    
    list_per_page = 10
    list_display = [
        "pid",
        "collection",
        "migration_status",
        "isis_updated_date",
        "updated",
        "created",
    ]
    list_filter = [
        "migration_status",
        "collection",
    ]
    search_fields = ["pid", "collection__acron", "collection__name"]
    inspect_view_fields = [
        "updated",
        "created",
        "migration_status",
        "isis_created_date",
        "isis_updated_date",
        "data",
    ]


class MigratedFileViewSet(SnippetViewSet):
    model = MigratedFile
    menu_label = _("Migrated files")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    inspect_view_enabled = True
    
    list_per_page = 10
    list_display = [
        "original_path",
        "collection",
        "created",
        "updated",
    ]
    list_filter = [
        "collection",
    ]
    search_fields = [
        "original_path",
        "collection__acron",
        "collection__name",
    ]
    inspect_view_fields = [
        "collection",
        "original_path",
        "file",
        "created",
        "updated",
    ]


class IdFileRecordViewSet(SnippetViewSet):
    model = IdFileRecord
    menu_label = _("Article id file")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    
    list_per_page = 10
    list_display = [
        "item_pid",
        "item_type",
        "parent__journal_acron",
        "todo",
        "updated",
        "created",
    ]
    list_filter = [
        "item_type",
        "todo",
        "parent__collection",
        "parent__journal_acron",
    ]
    search_fields = [
        "item_pid",
        "parent__journal_acron",
        "parent__collection__acron",
        "parent__collection__name",
    ]


class MigrationViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Migration")
    menu_icon = "folder-open-inverse"
    menu_order = get_menu_order("migration")
    items = (
        ClassicWebsiteConfigurationViewSet,
        MigratedDataViewSet,
        MigratedJournalViewSet,
        MigratedIssueViewSet,
        MigratedArticleViewSet,
        MigratedFileViewSet,
        IdFileRecordViewSet,    
    )


# Registra o grupo de snippets
register_snippet(MigrationViewSetGroup)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("migration/", include("migration.urls", namespace="migration")),
    ]
