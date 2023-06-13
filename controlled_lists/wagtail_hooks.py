from django.urls import path
from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail import hooks

from .button_helper import IndexedAtHelper
from .models import IndexedAt, IndexedAtFile
from .views import import_file, validate


class IndexedAtAdmin(ModelAdmin):
    model = IndexedAt
    menu_label = "Indexed At"
    menu_icon = "folder"
    menu_order = 100
    add_to_settings_menu = False
    exclude_from_explorer = False
    list_display = ("name", "acronym", "url", "description", "type")
    list_filter = ("type",)
    search_fields = ("name", "acronym")
    list_export = ("name", "acronym", "url", "description", "type")
    export_filename = "indexed_at"


class IndexedAtFileAdmin(ModelAdmin):
    model = IndexedAtFile
    button_helper_class = IndexedAtHelper
    menu_label = "Indexed At Upload"
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False
    list_display = ("attachment", "line_count", "is_valid")
    list_filter = ("is_valid",)
    search_fields = ("attachment",)


class IndexedAtAdminGroup(ModelAdminGroup):
    menu_label = "Indexed At"
    menu_icon = "folder-open-inverse"  # change as required
    menu_order = 200  # will put in 3rd place (000 being 1st, 100 2nd)
    items = (
        IndexedAtAdmin,
        IndexedAtFileAdmin,
    )


modeladmin_register(IndexedAtAdminGroup)


@hooks.register("register_admin_urls")
def register_calendar_url():
    return [
        path("controlled_lists/indexedatfile/validate", validate, name="validate"),
        path(
            "controlled_lists/indexedatfile/import_file",
            import_file,
            name="import_file",
        ),
    ]
