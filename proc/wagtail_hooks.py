from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSetGroup

from config.menu import get_menu_order
from core.views import CommonControlFieldViewSet
from htmlxml.models import HTMLXML
from package.models import SPSPkg

from .models import ArticleProc, IssueProc, JournalProc, ProcReport


class JournalProcViewSet(CommonControlFieldViewSet):
    model = JournalProc
    menu_label = _("Journal Processing")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    
    list_display = [
        "journal",
        "pid",
        "availability_status",
        "migration_status",
        "qa_ws_status",
        "public_ws_status",
        "updated",
    ]
    list_filter = [
        "collection",
        "availability_status",
        "migration_status",
        "qa_ws_status",
        "public_ws_status",
    ]
    search_fields = [
        "acron",
        "pid",
        "journal__title",
        "journal__official_journal__issn_print",
        "journal__official_journal__issn_electronic",
    ]


class IssueProcViewSet(CommonControlFieldViewSet):
    model = IssueProc
    inspect_view_enabled = True
    menu_label = _("Issue Processing")
    
    menu_icon = "folder"
    menu_order = 300
    add_to_settings_menu = False

    list_display = [
        "issue",
        "docs_status",
        "files_status",
        "qa_ws_status",
        "public_ws_status",
        "updated",
    ]
    list_filter = [
        "collection",
        "migration_status",
        "docs_status",
        "files_status",
        "qa_ws_status",
        "public_ws_status",
        "issue__publication_year",
    ]
    search_fields = [
        "journal_proc__acron",
        "journal_proc__journal__title",
        "issue_folder",
        "issue__publication_year",
        "issue__volume",
        "issue__number",
        "issue__supplement",
        "pid",
    ]


class HTMLXMLViewSet(CommonControlFieldViewSet):
    model = HTMLXML
    menu_label = _("XML from HTML")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    inspect_view_enabled = True

    list_per_page = 10

    list_display = [
        "migrated_article",
        "html2xml_status",
        "quality",
        "attention_demands",
        "html_translation_langs",
        "pdf_langs",
        "n_paragraphs",
        "n_references",
        "created_updated",
    ]
    list_filter = [
        "html2xml_status",
        "quality",
        "pdf_langs",
        "html_translation_langs",
        "article_type",
        "empty_body",
        "html_img_total",
        "html_table_total",
        "attention_demands",
    ]
    search_fields = [
        "migrated_article__pid",
        "html2xml_status",
        "article_type",
    ]


class SPSPkgViewSet(CommonControlFieldViewSet):
    model = SPSPkg
    menu_label = _("SPS Package")
    inspect_view_enabled = True
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 10

    list_display = [
        "sps_pkg_name",
        "pid_v3",
        "registered_in_core",
        "valid_texts",
        "valid_components",
        "is_public",
        "xml_uri",
        "created",
        "updated",
    ]

    list_filter = [
        "origin",
        "registered_in_core",
        "valid_texts",
        "valid_components",
        "is_public",
    ]

    search_fields = [
        "pid_v3",
        "sps_pkg_name",
    ]


class ArticleProcViewSet(CommonControlFieldViewSet):
    model = ArticleProc
    menu_label = _("Article Processing")
    inspect_view_enabled = True
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 10
    
    list_display = [
        "__str__",
        "migration_status",
        "xml_status",
        "sps_pkg_status",
        "qa_ws_status",
        "public_ws_status",
        "updated",
    ]
    list_filter = [
        "collection",
        "migration_status",
        "xml_status",
        "sps_pkg_status",
        "qa_ws_status",
        "public_ws_status",
    ]
    search_fields = [
        "sps_pkg__pid_v3",
        "pid",
        "sps_pkg__sps_pkg_name",
        "pkg_name",
        "issue_proc__issue_folder",
        "issue_proc__journal_proc__acron",
    ]


class ProcReportViewSet(CommonControlFieldViewSet):
    model = ProcReport
    menu_label = _("Processing Report")
    inspect_view_enabled = True
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False

    list_per_page = 50

    list_display = [
        "pid",
        "collection",
        "task_name",
        "report_date",
        "updated",
        "created",
    ]
    list_filter = [
        "task_name",
        "collection",
        "item_type",
    ]
    search_fields = [
        "pid",
        "collection__name",
        "task_name",
        "report_date",
    ]


class ProcessViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Processing")
    menu_icon = "folder-open-inverse"
    menu_order = get_menu_order("processing")
    items = (
        JournalProcViewSet,
        IssueProcViewSet,
        ArticleProcViewSet,
        SPSPkgViewSet,
        HTMLXMLViewSet,
        ProcReportViewSet,
    )


# Registra o grupo de snippets
register_snippet(ProcessViewSetGroup)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("proc/", include("proc.urls", namespace="proc")),
    ]