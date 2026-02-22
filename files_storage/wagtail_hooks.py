from django.utils.translation import gettext_lazy as _
from wagtail.snippets.views.snippets import SnippetViewSet

from config.menu import get_menu_order
from files_storage.models import MinioConfiguration


class MinioConfigurationViewSet(SnippetViewSet):
    model = MinioConfiguration
    menu_label = _("Minio Configuration")
    menu_icon = "folder"
    menu_order = get_menu_order("files_storage")
    # no menu, ficará disponível como sub-menu em "Settings"
    add_to_settings_menu = True

    list_per_page = 10
    list_display = (
        "name",
        "host",
        "bucket_root",
    )
    search_fields = (
        "name",
        "host",
        "bucket_root",
    )

