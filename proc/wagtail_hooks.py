from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import include, path
from django.utils.translation import gettext as _
from wagtail import hooks
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.contrib.modeladmin.views import CreateView, InspectView

from config.menu import get_menu_order
from package.models import SPSPkg

from .models import ArticleProc, IssueProc, JournalProc


class ProcCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class JournalProcModelAdmin(ModelAdmin):
    model = JournalProc
    menu_label = _("Journal Processing")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "acron",
        "journal",
        "migration_status",
        "qa_ws_status",
        "public_ws_status",
        "updated",
        "created",
    )
    list_filter = (
        "error_found",
        "availability_status",
        "migration_status",
        "qa_ws_status",
        "public_ws_status",
    )
    search_fields = (
        "acron",
        "availability_status",
        "scielo_issn",
        "title",
    )


class IssueProcModelAdmin(ModelAdmin):
    model = IssueProc
    inspect_view_enabled = True
    menu_label = _("Issue Processing")
    create_view_class = ProcCreateView
    menu_icon = "folder"
    # menu_order = get_menu_order("issue")
    menu_order = 300
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "issue",
        "docs_status",
        "files_status",
        "qa_ws_status",
        "public_ws_status",
        "updated",
        "created",
    )
    list_filter = (
        "error_found",
        "migration_status",
        "docs_status",
        "files_status",
        "qa_ws_status",
        "public_ws_status",
        "issue__publication_year",
    )
    search_fields = (
        "journal_proc__acron",
        "issue_folder",
        "issue__publication_year",
        "issue__volume",
        "issue__number",
        "issue__supplement",
    )


class SPSPkgModelAdmin(ModelAdmin):
    model = SPSPkg
    menu_label = _("SPS Package")
    inspect_view_enabled = True
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "pid_v3",
        "sps_pkg_name",
        "xml_uri",
        "created",
        "updated",
    )

    list_filter = (
        "origin",
        "is_pid_provider_synchronized",
        "valid_texts",
        "valid_components",
        "is_public",
    )

    search_fields = (
        "pid_v3",
        "sps_pkg_name",
        "scheduled",
    )


class ArticleProcModelAdmin(ModelAdmin):
    model = ArticleProc
    menu_label = _("Article Processing")
    inspect_view_enabled = True
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "issue_proc",
        "pkg_name",
        "xml_status",
        "sps_pkg_status",
        "qa_ws_status",
        "public_ws_status",
        "updated",
        "created",
    )
    list_filter = (
        "error_found",
        "migration_status",
        "xml_status",
        "sps_pkg_status",
        "qa_ws_status",
        "public_ws_status",
    )
    search_fields = (
        "sps_pkg__pid_v3",
        "pid",
        "sps_pkg__sps_pkg_name",
        "pkg_name",
    )


class ProcessModelAdminGroup(ModelAdminGroup):
    menu_label = _("Processing")
    menu_icon = "folder-open-inverse"
    # menu_order = get_menu_order("article")
    menu_order = 400
    items = (
        JournalProcModelAdmin,
        IssueProcModelAdmin,
        ArticleProcModelAdmin,
        SPSPkgModelAdmin,
    )


modeladmin_register(ProcessModelAdminGroup)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("proc/", include("proc.urls", namespace="proc")),
    ]
