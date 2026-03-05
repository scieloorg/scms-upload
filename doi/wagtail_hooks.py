"""
Wagtail admin hooks for the DOI app.
"""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from config.menu import get_menu_order
from core.views import CommonControlFieldViewSet
from doi.models import CrossrefConfiguration, CrossrefDeposit


class CrossrefConfigurationViewSet(CommonControlFieldViewSet):
    model = CrossrefConfiguration
    menu_label = _("Crossref Configuration")
    menu_icon = "cog"
    menu_order = 100
    add_to_settings_menu = False
    inspect_view_enabled = True

    list_display = [
        "journal",
        "depositor_name",
        "depositor_email",
        "registrant",
        "updated",
    ]
    list_filter = []
    search_fields = [
        "journal__title",
        "journal__journal_acron",
        "depositor_name",
        "registrant",
    ]
    list_per_page = 20


class CrossrefDepositViewSet(CommonControlFieldViewSet):
    model = CrossrefDeposit
    menu_label = _("Crossref Deposits")
    menu_icon = "upload"
    menu_order = 200
    add_to_settings_menu = False
    inspect_view_enabled = True

    list_display = [
        "article",
        "status",
        "batch_id",
        "response_status",
        "updated",
    ]
    list_filter = ["status"]
    search_fields = [
        "article__pid_v3",
        "article__pid_v2",
        "batch_id",
    ]
    list_per_page = 20


class CrossrefViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Crossref")
    menu_icon = "site"
    menu_order = get_menu_order("doi")

    items = [
        CrossrefConfigurationViewSet,
        CrossrefDepositViewSet,
    ]


register_snippet(CrossrefViewSetGroup)
