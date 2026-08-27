from django.utils.translation import gettext_lazy as _
from wagtail.admin.ui.tables import UpdatedAtColumn
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from core.users.permission_policies import SuperuserOnlySnippetViewSetMixin
from tracker.models import TaskTracker, UnexpectedEvent


class UnexpectedEventViewSet(SuperuserOnlySnippetViewSetMixin, SnippetViewSet):
    model = UnexpectedEvent
    menu_icon = "warning"
    menu_label = _("Unexpected Events")
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 10

    list_display = [
        "item",
        "action",
        "exception_type",
        "exception_msg",
        "created",
    ]

    list_filter = [
        "action",
        "exception_type",
        "created",
    ]

    search_fields = [
        "exception_msg",
        "detail",
        "action",
        "item",
    ]

    # Campos para a view de inspeção (read-only)
    inspect_view_enabled = True
    inspect_view_fields = [
        "action",
        "item",
        "exception_type",
        "exception_msg",
        "traceback",
        "detail",
        "created",
    ]


class TaskTrackerViewSet(SuperuserOnlySnippetViewSetMixin, SnippetViewSet):
    model = TaskTracker
    menu_icon = "tasks"
    menu_label = _("Event Tracker")
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 10

    list_display = [
        "name",
        "item",
        "total_to_process",
        "total_processed",
        "status",
        "created",
        UpdatedAtColumn(),  # Coluna especial para 'updated'
    ]

    list_filter = [
        "status",
        "name",
        "created",
        "updated",
    ]

    search_fields = ["name", "item"]

    # View de inspeção
    inspect_view_enabled = True
    inspect_view_fields = [
        "name",
        "item",
        "status",
        "created",
        "updated",
    ]


class TrackerViewSetGroup(SnippetViewSetGroup):
    items = [
        TaskTrackerViewSet,
        UnexpectedEventViewSet,
    ]
    menu_icon = "folder"
    menu_label = _("Event Monitoring")
    menu_order = 1


register_snippet(TrackerViewSetGroup)
