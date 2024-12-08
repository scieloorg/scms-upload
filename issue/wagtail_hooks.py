from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from issue.views import IssueCreateView, TOCEditView
from config.menu import get_menu_order

from .models import TOC, Issue


class IssueAdmin(ModelAdmin):
    model = Issue
    inspect_view_enabled = True
    menu_label = _("Issues")
    create_view_class = IssueCreateView
    menu_icon = "folder"
    menu_order = get_menu_order("issue")
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "journal",
        "publication_year",
        "order",
        "volume",
        "number",
        "supplement",
    )
    list_filter = ("publication_year",)
    search_fields = (
        "journal__official_journal__title",
        "journal__official_journal__issn_electronic",
        "journal__official_journal__issn_print",
        "publication_year",
        "volume",
        "number",
        "supplement",
    )

    # def get_ordering(self, request):
    #     qs = super().get_queryset(request)
    #     # Only show people managed by the current user
    #     return qs.order_by("-updated")


class TOCAdmin(ModelAdmin):
    model = TOC
    inspect_view_enabled = True
    menu_label = _("Table of contents sections")
    edit_view_class = TOCEditView
    menu_icon = "folder"
    menu_order = get_menu_order("issue")
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "issue",
        "creator",
        "created",
        "updated_by",
        "updated",
    )
    list_filter = ("ordered",)
    search_fields = (
        "issue__journal__title",
        "issue__journal__official_journal__title",
        "issue__volume",
        "issue__number",
        "issue__supplement",
        "issue__publication_year",
    )


class IssueModelAdminGroup(ModelAdminGroup):
    menu_icon = "folder"
    menu_label = _("Issues")
    menu_order = get_menu_order("issue")
    items = (
        IssueAdmin,
        TOCAdmin,
    )


modeladmin_register(IssueModelAdminGroup)
