from django.contrib.admin.utils import unquote
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import get_object_or_404
from wagtail.permission_policies import ModelPermissionPolicy
from wagtail.snippets.views.snippets import (
    CopyView,
    DeleteView,
    EditView,
    HistoryView,
    InspectView,
    RevisionsCompareView,
    RevisionsUnscheduleView,
    UnpublishView,
    UsageView,
)

from core.users.scoped_queryset import scope_by_membership
from team.authorization import user_app_access


class TeamModelPermissionPolicy(ModelPermissionPolicy):
    def _check_app_access(self, user, action):
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        access = user_app_access(user, self.app_label)
        if not access or access == "none":
            return False
        if access == "read" and action != "view":
            return False
        return True

    def user_has_permission(self, user, action):
        if not self._check_app_access(user, action):
            return False
        return super().user_has_permission(user, action)

    def user_has_any_permission(self, user, actions):
        if user and user.is_superuser:
            return super().user_has_any_permission(user, actions)
        access = user_app_access(user, self.app_label)
        if not access or access == "none":
            return False
        if access == "read":
            return "view" in actions and super().user_has_permission(user, "view")
        return super().user_has_any_permission(user, actions)


class SuperuserOnlyModelPermissionPolicy(ModelPermissionPolicy):
    def user_has_permission(self, user, action):
        return bool(
            user
            and user.is_superuser
            and super().user_has_permission(user, action)
        )

    def user_has_any_permission(self, user, actions):
        return bool(
            user
            and user.is_superuser
            and super().user_has_any_permission(user, actions)
        )


class TeamScopedViewBase:
    viewset = None

    def get_queryset(self):
        if self.viewset:
            return self.viewset.get_queryset(self.request)
        return super().get_queryset()


class TeamScopedEditView(TeamScopedViewBase, EditView):
    def save_instance(self):
        instance = self.form.save(commit=False)
        if hasattr(instance, "updated_by"):
            instance.updated_by = self.request.user
        instance.save()
        if hasattr(self.form, "save_m2m"):
            self.form.save_m2m()
        return instance


class TeamScopedDeleteView(TeamScopedViewBase, DeleteView):
    pass


class TeamScopedInspectView(TeamScopedViewBase, InspectView):
    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        return get_object_or_404(queryset, pk=unquote(str(self.pk)))


class TeamScopedCopyView(TeamScopedViewBase, CopyView):
    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        return get_object_or_404(
            queryset, pk=unquote(str(self.kwargs[self.pk_url_kwarg]))
        )


class TeamScopedHistoryView(TeamScopedViewBase, HistoryView):
    pass


class TeamScopedRevisionsCompareView(TeamScopedViewBase, RevisionsCompareView):
    pass


class TeamScopedRevisionsUnscheduleView(TeamScopedViewBase, RevisionsUnscheduleView):
    pass


class TeamScopedUsageView(TeamScopedViewBase, UsageView):
    pass


class TeamScopedUnpublishView(TeamScopedViewBase, UnpublishView):
    pass


class TeamScopedSnippetViewSetMixin:
    journal_field = None
    collection_field = None
    company_field = None
    scope_policy = None
    allow_unscoped_queryset = False

    edit_view_class = TeamScopedEditView
    delete_view_class = TeamScopedDeleteView
    inspect_view_class = TeamScopedInspectView
    copy_view_class = TeamScopedCopyView
    history_view_class = TeamScopedHistoryView
    revisions_compare_view_class = TeamScopedRevisionsCompareView
    revisions_unschedule_view_class = TeamScopedRevisionsUnscheduleView
    usage_view_class = TeamScopedUsageView
    unpublish_view_class = TeamScopedUnpublishView

    @property
    def permission_policy(self):
        return TeamModelPermissionPolicy(self.model)

    def get_common_view_kwargs(self, **kwargs):
        view_kwargs = super().get_common_view_kwargs(**kwargs)
        view_kwargs["viewset"] = self
        return view_kwargs

    def _validate_scope_configuration(self):
        has_field_scope = bool(
            self.journal_field
            or self.collection_field
            or self.company_field
        )
        has_policy_scope = self.scope_policy is not None
        has_global_opt_in = bool(self.allow_unscoped_queryset)

        modes = [has_field_scope, has_policy_scope, has_global_opt_in]

        if sum(modes) != 1:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} must configure exactly one scoping strategy: "
                f"relational fields (collection_field, journal_field, company_field), "
                f"scope_policy, or allow_unscoped_queryset=True (configured: {sum(modes)})"
            )

    def get_queryset(self, request):
        self._validate_scope_configuration()

        qs = super().get_queryset(request)
        if qs is None:
            qs = self.model._default_manager.all()

        if request.user and request.user.is_superuser:
            return qs

        access = user_app_access(request.user, self.model._meta.app_label)
        if not access or access == "none":
            return qs.none()

        if self.scope_policy:
            return self.scope_policy.scope_queryset(request.user, qs).distinct()

        if self.journal_field or self.collection_field or self.company_field:
            return scope_by_membership(
                request.user,
                qs,
                journal_field=self.journal_field,
                collection_field=self.collection_field,
                company_field=self.company_field,
            ).distinct()

        return qs


class SuperuserOnlySnippetViewSetMixin(TeamScopedSnippetViewSetMixin):
    allow_unscoped_queryset = True

    @property
    def permission_policy(self):
        return SuperuserOnlyModelPermissionPolicy(self.model)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user and request.user.is_superuser:
            return queryset
        return queryset.none()
