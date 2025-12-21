from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail.admin.ui.tables import UpdatedAtColumn
from tracker.models import UnexpectedEvent, TaskTracker

 
class UnexpectedEventViewSet(SnippetViewSet):
    model = UnexpectedEvent
    menu_icon = 'warning'
    menu_label = _("Unexpected Events")
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 10
    
    list_display = [
        'item',
        'action', 
        'exception_type',
        'exception_msg',
        'created',
    ]
    
    list_filter = [
        'action',
        'exception_type',
        'created',
    ]
    
    search_fields = [
        'exception_msg',
        'detail',
        'action',
        'item',
    ]
    
    # Campos para a view de inspeção (read-only)
    inspect_view_enabled = True
    inspect_view_fields = [
        'action',
        'item',
        'exception_type',
        'exception_msg',
        'traceback',
        'detail',
        'created',
    ]


class TaskTrackerViewSet(SnippetViewSet):
    model = TaskTracker
    menu_icon = 'tasks'
    menu_label = _("Event Tracker")
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 10
    
    list_display = [
        'name',
        'item',
        "total_to_process",
        "total_processed",
        'status',
        'created',
        UpdatedAtColumn(),  # Coluna especial para 'updated'
    ]
    
    list_filter = [
        'status',
        'name',
        'created',
        'updated',
    ]
    
    search_fields = ['name', 'item']
    
    # View de inspeção
    inspect_view_enabled = True
    inspect_view_fields = [
        'name',
        'item', 
        'status',
        'created',
        'updated',
    ]


class TrackerViewSetGroup(SnippetViewSetGroup):
    """
    Grupo de ViewSets para Event Monitoring
    """
    items = [
        TaskTrackerViewSet,
        UnexpectedEventViewSet,
    ]
    menu_icon = 'folder'
    menu_label = _("Event Monitoring")
    menu_order = 1  # ou use get_menu_order("unexpected-error")


register_snippet(TrackerViewSetGroup)