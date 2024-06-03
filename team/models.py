import logging

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel, ObjectList, TabbedInterface
from wagtailautocomplete.edit_handlers import AutocompletePanel

from collection.models import Collection
from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from team.forms import CollectionTeamMemberModelForm
User = get_user_model()


class TeamMember(CommonControlField):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    is_active_member = models.BooleanField(
        null=True, blank=True, default=True
    )

    panels = [
        FieldPanel("user"),
        FieldPanel("is_active_member"),
    ]

    @staticmethod
    def autocomplete_custom_queryset_filter(text):
        return TeamMember.objects.filter(
            Q(user__username__icontains=text) |
            Q(user__email__icontains=text) |
            Q(user__name__icontains=text))

    def autocomplete_label(self):
        return str(self.user)

    class Meta:
        abstract = True
        verbose_name = _("Team")
        verbose_name_plural = _("Teams")
        indexes = [
            models.Index(
                fields=[
                    "is_active_member",
                ]
            ),
        ]


class CollectionTeamMember(TeamMember):
    collection = models.ForeignKey(Collection, null=True, blank=True, on_delete=models.SET_NULL)

    base_form_class = CollectionTeamMemberModelForm
    panels = [
        AutocompletePanel("collection"),
        AutocompletePanel("user"),
        FieldPanel("is_active_member"),
    ]

    class Meta:
        verbose_name = _("Team member")
        verbose_name_plural = _("Team members")
        unique_together = ("user", "collection")

    @staticmethod
    def autocomplete_custom_queryset_filter(text):
        return CollectionTeamMember.objects.filter(
            Q(user__username__icontains=text) |
            Q(user__email__icontains=text) |
            Q(user__name__icontains=text))

    def autocomplete_label(self):
        return str(self.user)

    @staticmethod
    def collections(user, is_active_member=None):
        try:
            if is_active_member:
                for member in CollectionTeamMember.objects.filter(
                    user=user, is_active_member=is_active_member):
                    yield member.collection
            else:
                for member in CollectionTeamMember.objects.filter(
                    user=user):
                    yield member.collection
        except Exception as e:
            return Collection.objects.all()

    @staticmethod
    def members(user, is_active_member=None):
        for collection in CollectionTeamMember.collections(user, is_active_member):
            return CollectionTeamMember.objects.filter(collection=collection)
