import json

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import include, path
from django.utils.translation import gettext as _
from wagtail import hooks
from wagtail_modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)

from config.menu import get_menu_order
from team.views import CollectionTeamMemberCreateView

from .models import CollectionTeamMember


class CollectionTeamMemberModelAdmin(ModelAdmin):
    model = CollectionTeamMember
    menu_label = _("Collection Team Members")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False
    create_view_class = CollectionTeamMemberCreateView

    list_display = (
        "user",
        "is_active_member",
        "collection",
        "updated",
    )
    list_filter = ("is_active_member", "collection")
    search_fields = (
        "collection__name",
        "collection__acron",
        "user__name",
    )

    def get_queryset(self, request):
        if request.user.is_superuser:
            return super().get_queryset(request)
        return CollectionTeamMember.members(request.user)


class TeamModelAdminGroup(ModelAdminGroup):
    menu_icon = "folder"
    menu_label = _("Teams")
    items = (CollectionTeamMemberModelAdmin,)
    menu_order = get_menu_order("team")


modeladmin_register(TeamModelAdminGroup)


# @hooks.register("register_admin_urls")
# def register_disclosure_url():
#     return [
#         path("team/", include("team.urls", namespace="team")),
#     ]
