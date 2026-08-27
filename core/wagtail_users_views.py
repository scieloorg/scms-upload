from django import forms
from django.utils.translation import gettext_lazy as _
from wagtail.users.forms import GroupForm, UserCreationForm, UserEditForm
from wagtail.users.views.groups import DeleteView, EditView, GroupViewSet, IndexView
from wagtail.users.views.users import UserViewSet

from team.constants import TeamGroups

_PROTECTED_GROUP_NAMES = set(TeamGroups.ALL)


class CanonicalGroupsExcludedMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["groups"].queryset = self.fields["groups"].queryset.exclude(
            name__in=_PROTECTED_GROUP_NAMES
        )


class ProtectedUserCreationForm(CanonicalGroupsExcludedMixin, UserCreationForm):
    pass


class ProtectedUserEditForm(CanonicalGroupsExcludedMixin, UserEditForm):
    def clean_groups(self):
        selected_groups = list(self.cleaned_data["groups"])
        canonical_groups = self.instance.groups.filter(name__in=_PROTECTED_GROUP_NAMES)
        return selected_groups + list(canonical_groups)


class ProtectedUserViewSet(UserViewSet):
    def get_form_class(self, for_update=False):
        if for_update:
            return ProtectedUserEditForm
        return ProtectedUserCreationForm


class ProtectedGroupForm(GroupForm):
    def clean_name(self):
        name = self.cleaned_data["name"]
        if name in _PROTECTED_GROUP_NAMES and (
            self.instance.pk is None or self.instance.name != name
        ):
            raise forms.ValidationError(
                _(
                    "This group name is reserved for system use and cannot be used manually."
                )
            )
        return name


class ProtectedGroupIndexView(IndexView):
    def get_queryset(self):
        return super().get_queryset().exclude(name__in=_PROTECTED_GROUP_NAMES)


class ProtectedGroupEditView(EditView):
    def get_queryset(self):
        return super().get_queryset().exclude(name__in=_PROTECTED_GROUP_NAMES)


class ProtectedGroupDeleteView(DeleteView):
    def get_queryset(self):
        return super().get_queryset().exclude(name__in=_PROTECTED_GROUP_NAMES)


class ProtectedGroupViewSet(GroupViewSet):
    index_view_class = ProtectedGroupIndexView
    edit_view_class = ProtectedGroupEditView
    delete_view_class = ProtectedGroupDeleteView

    def get_form_class(self, for_update=False):
        return ProtectedGroupForm
