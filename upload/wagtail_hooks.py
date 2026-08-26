import logging

from django.contrib.admin.utils import quote
from django.db.models import Q
from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.ui.tables import TitleColumn
from wagtail.admin.widgets import ListingButton
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import IndexView as SnippetIndexView
from wagtail.snippets.views.snippets import SnippetViewSetGroup

from config.menu import get_menu_order
from core.users.permission_policies import (
    TeamScopedCopyView,
    TeamScopedDeleteView,
    TeamScopedEditView,
    TeamScopedHistoryView,
    TeamScopedInspectView,
    TeamScopedRevisionsCompareView,
    TeamScopedRevisionsUnscheduleView,
    TeamScopedUnpublishView,
    TeamScopedUsageView,
)
from core.users.scoped_queryset import scope_by_membership
from core.views import CommonControlFieldViewSet
from upload.admin_buttons import get_package_action_buttons
from upload.bulk_actions.republish import (
    RepublishPublicBulkAction,
    RepublishQABulkAction,
)
from upload.permission_policies import UploadModelPermissionPolicy
from upload.permissions import ACCESS_PACKAGES
from upload.querysets import get_scoped_package_queryset, scope_package_queryset
from upload.views import (
    PackageAdminInspectView,
    PackageZipCreateView,
    QAPackageEditView,
    ReadyToPublishPackageEditView,
    ValidationReportEditView,
    XMLErrorReportEditView,
    XMLInfoReportEditView,
)

from .models import (
    ArchivedPackage,
    Package,
    PackageZip,
    PkgValidationResult,
    QAPackage,
    ReadyToPublishPackage,
    UploadValidator,
    ValidationReport,
    XMLError,
    XMLErrorReport,
    XMLInfo,
    XMLInfoReport,
    choices,
)

MODEL_PERMISSION_ACTIONS = ("add", "change", "delete", "view")


class PackageActionIndexView(SnippetIndexView):
    def get_list_more_buttons(self, instance):
        buttons = super().get_list_more_buttons(instance)
        buttons.extend(
            get_package_action_buttons(
                self.request.user,
                instance,
                ListingButton,
            )
        )

        return buttons


class InspectFirstPackageIndexView(PackageActionIndexView):
    def _get_title_column(self, field_name, column_class=TitleColumn, **kwargs):
        column_class = self._get_title_column_class(column_class)

        def get_url(instance):
            if inspect_url := self.get_inspect_url(instance):
                return inspect_url
            return self.get_edit_url(instance)

        kwargs.setdefault(
            "get_title_id",
            lambda instance: f"snippet_{quote(instance.pk)}_title",
        )

        if not self.model:
            return column_class(
                "name", label="Name", accessor=str, get_url=get_url, **kwargs
            )
        return self._get_custom_column(
            field_name, column_class, get_url=get_url, **kwargs
        )


hooks.register("register_bulk_action", RepublishQABulkAction)
hooks.register("register_bulk_action", RepublishPublicBulkAction)


class BaseUploadViewSet(CommonControlFieldViewSet):
    denied_permission_actions = ()
    package_scope_field = None
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
        return UploadModelPermissionPolicy(
            self.model,
            denied_actions=self.denied_permission_actions,
        )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not self.permission_policy.user_has_any_permission(
            request.user,
            MODEL_PERMISSION_ACTIONS,
        ):
            return queryset.none()

        if self.package_scope_field:
            package_scope = get_scoped_package_queryset(request.user)
            queryset = queryset.filter(
                **{f"{self.package_scope_field}__in": package_scope}
            )

        return queryset

    def get_common_view_kwargs(self, **kwargs):
        view_kwargs = super().get_common_view_kwargs(**kwargs)
        view_kwargs["viewset"] = self
        return view_kwargs


class PackageZipViewSet(BaseUploadViewSet):
    model = PackageZip
    add_view_class = PackageZipCreateView
    menu_label = _("Package upload")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 20

    list_display = (
        "name",
        "__str__",
        "creator",
        "updated",
    )
    list_filter = ("creator",)
    search_fields = (
        "name",
        "file",
        "creator__username",
        "updated_by__username",
    )

    def get_queryset(self, request):
        if request.user.is_superuser:
            return super().get_queryset(request)

        qs = super().get_queryset(request)
        if request.user.has_perm(f"upload.{ACCESS_PACKAGES}"):
            package_scope = get_scoped_package_queryset(request.user)
            return qs.filter(
                Q(creator=request.user) | Q(packages__in=package_scope)
            ).distinct()

        return qs.filter(creator=request.user)


class PackageViewSet(BaseUploadViewSet):
    model = Package
    denied_permission_actions = ("delete",)

    index_view_class = InspectFirstPackageIndexView

    inspect_view_enabled = True
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = "modeladmin/upload/package/inspect.html"
    menu_label = _("Package admin")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 20

    list_display = (
        "__str__",
        "xml_errors_percentage",
        "category",
        "status",
        "creator",
        "updated",
        "expiration_date",
    )
    list_filter = (
        "blocking_errors",
        "critical_errors",
        "category",
        "status",
    )
    search_fields = (
        "name",
        "journal__official_journal__title",
        "issue__journal__official_journal__title",
        "article__pid_v3",
        "creator__username",
        "updated_by__username",
        "pkg_zip__file",
    )
    inspect_view_fields = (
        "article",
        "issue",
        "category",
        "status",
        "file",
        "created",
        "updated",
        "expiration_date",
        "files_list",
    )

    def get_queryset(self, request):
        params = {}
        try:
            params["pkg_zip_id"] = request.GET["pkg_zip_id"]
        except KeyError:
            logging.info(request.GET)

        status = [
            choices.PS_ENQUEUED_FOR_VALIDATION,
            choices.PS_VALIDATED_WITH_ERRORS,
            choices.PS_PENDING_CORRECTION,
            choices.PS_UNEXPECTED,
            choices.PS_REQUIRED_ERRATUM,
            choices.PS_REQUIRED_UPDATE,
            choices.PS_PENDING_QA_DECISION,
            choices.PS_READY_TO_PREVIEW,
            choices.PS_PREVIEW,
            choices.PS_READY_TO_PUBLISH,
            choices.PS_PUBLISHED,
        ]

        qs = super().get_queryset(request).filter(status__in=status, **params)
        return scope_package_queryset(qs, request.user)


class QualityAnalysisPackageViewSet(BaseUploadViewSet):
    model = QAPackage
    denied_permission_actions = ("delete",)
    index_view_class = PackageActionIndexView
    menu_label = _("Quality control admin")
    menu_icon = "folder"
    menu_order = 200
    edit_view_class = QAPackageEditView
    inspect_view_enabled = True
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = "modeladmin/upload/package/inspect.html"
    add_to_settings_menu = False
    list_per_page = 20

    list_display = (
        "name",
        "creator",
        "assignee",
        "xml_errors_percentage",
        "status",
        "updated",
    )
    list_filter = (
        "creator",
        "status",
        "category",
    )
    search_fields = (
        "name",
        "file",
        "assignee__username",
        "analyst__user__username",
        "creator__username",
        "updated_by__username",
        "assignee__email",
        "analyst__user__email",
        "creator__email",
        "updated_by__email",
    )

    def get_queryset(self, request):
        status = [
            choices.PS_VALIDATED_WITH_ERRORS,
            choices.PS_PENDING_CORRECTION,
            choices.PS_PENDING_QA_DECISION,
        ]
        params = {
            "blocking_errors": 0,
        }
        qs = super().get_queryset(request).filter(status__in=status, **params)
        if not request.user.is_superuser:
            qs = qs.filter(
                Q(assignee__isnull=True) | Q(assignee=request.user),
            )

        return scope_package_queryset(qs, request.user)


class ReadyToPublishPackageViewSet(BaseUploadViewSet):
    model = ReadyToPublishPackage
    denied_permission_actions = ("delete",)
    menu_label = _("Publication admin")
    menu_icon = "folder"
    menu_order = 200
    edit_view_class = ReadyToPublishPackageEditView
    inspect_view_enabled = True
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = "modeladmin/upload/package/inspect.html"
    add_to_settings_menu = False
    list_per_page = 20

    list_display = (
        "__str__",
        "assignee",
        "analyst",
        "toc_sections",
        "order",
        "category",
        "status",
        "updated",
    )
    list_filter = (
        "creator",
        "status",
        "category",
    )
    search_fields = (
        "name",
        "file",
        "assignee__username",
        "analyst__user__username",
        "creator__username",
        "updated_by__username",
        "assignee__email",
        "analyst__user__email",
        "creator__email",
        "updated_by__email",
    )

    def get_queryset(self, request):
        status = [
            choices.PS_READY_TO_PREVIEW,
            choices.PS_PREVIEW,
            choices.PS_READY_TO_PUBLISH,
            choices.PS_PUBLISHED,
        ]
        params = {
            "blocking_errors": 0,
        }
        qs = super().get_queryset(request).filter(status__in=status, **params)

        return scope_package_queryset(qs, request.user)


class XMLErrorReportViewSet(BaseUploadViewSet):
    model = XMLErrorReport
    package_scope_field = "package"
    edit_view_class = XMLErrorReportEditView
    menu_label = _("XML Error Reports")
    menu_icon = "error"
    add_to_settings_menu = False
    list_display = (
        "package",
        "category",
        "title",
        "creation",
    )
    list_filter = (
        "category",
        "creation",
    )
    search_fields = (
        "title",
        "package__name",
        "package__file",
    )


class XMLErrorViewSet(BaseUploadViewSet):
    model = XMLError
    package_scope_field = "report__package"
    menu_label = _("XML errors")
    menu_icon = "error"
    add_to_settings_menu = False
    list_display = (
        "subject",
        "attribute",
        "focus",
        "message",
        "report",
    )
    list_filter = (
        "validation_type",
        "parent",
        "parent_id",
        "subject",
        "attribute",
    )
    search_fields = (
        "focus",
        "message",
        "advice",
        "package__name",
        "package__file",
    )


class XMLInfoReportViewSet(BaseUploadViewSet):
    model = XMLInfoReport
    package_scope_field = "package"
    edit_view_class = XMLInfoReportEditView
    menu_label = _("XML Info Reports")
    menu_icon = "error"
    add_to_settings_menu = False
    list_display = (
        "package",
        "category",
        "title",
        "creation",
    )
    list_filter = (
        "category",
        "creation",
    )
    search_fields = (
        "title",
        "package__name",
        "package__file",
    )


class XMLInfoViewSet(BaseUploadViewSet):
    model = XMLInfo
    package_scope_field = "report__package"
    menu_label = _("XML info")
    menu_icon = "error"
    add_to_settings_menu = False
    list_display = (
        "subject",
        "attribute",
        "focus",
        "message",
        "report",
    )
    list_filter = (
        "status",
        "validation_type",
        "parent",
        "parent_id",
        "subject",
        "attribute",
    )
    search_fields = (
        "focus",
        "message",
        "package__name",
        "package__file",
    )


class ValidationReportViewSet(BaseUploadViewSet):
    model = ValidationReport
    package_scope_field = "package"
    edit_view_class = ValidationReportEditView
    menu_label = _("Validation Reports")
    menu_icon = "error"
    add_to_settings_menu = False
    list_display = (
        "package",
        "category",
        "title",
        "creation",
    )
    list_filter = (
        "category",
        "creation",
    )
    search_fields = (
        "title",
        "package__name",
        "package__file",
    )


class ValidationViewSet(BaseUploadViewSet):
    model = PkgValidationResult
    package_scope_field = "report__package"
    menu_label = _("Validations")
    menu_icon = "error"
    add_to_settings_menu = False
    list_display = (
        "subject",
        "status",
        "message",
        "created",
    )
    list_filter = ("status",)
    search_fields = (
        "subject",
        "status",
        "message",
    )


class UploadValidatorViewSet(BaseUploadViewSet):
    model = UploadValidator
    menu_label = _("Upload Validator")
    menu_icon = "folder"
    add_to_settings_menu = False
    list_display = (
        "collection",
        "max_xml_warnings_percentage",
        "max_xml_errors_percentage",
        "max_impossible_to_fix_percentage",
        "decision_for_critical_errors",
    )
    list_filter = ("collection",)
    search_fields = (
        "collection__acron",
        "collection__name",
    )

    def get_queryset(self, request):
        return scope_by_membership(
            request.user,
            super().get_queryset(request),
            collection_field="collection",
        )


class ArchivedPackageViewSet(BaseUploadViewSet):
    model = ArchivedPackage
    denied_permission_actions = ("delete",)
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = "modeladmin/upload/package/inspect.html"
    menu_label = _("Archived Packages")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 20

    list_display = (
        "__str__",
        "critical_errors",
        "xml_errors_percentage",
        "category",
        "status",
        "creator",
        "updated",
        "expiration_date",
    )
    list_filter = (
        "creator",
        "category",
        "status",
    )
    search_fields = (
        "name",
        "journal__official_journal__title",
        "issue__journal__official_journal__title",
        "article__pid_v3",
        "creator__username",
        "updated_by__username",
        "pkg_zip__file",
    )
    inspect_view_fields = (
        "article",
        "issue",
        "category",
        "status",
        "file",
        "created",
        "updated",
        "expiration_date",
        "files_list",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request).filter(~Q(status__in=choices.PS_WIP))

        return scope_package_queryset(qs, request.user)


class UploadViewSetGroup(SnippetViewSetGroup):
    menu_icon = "folder"
    menu_label = "Upload"
    items = [
        PackageZipViewSet,
        PackageViewSet,
        QualityAnalysisPackageViewSet,
        ReadyToPublishPackageViewSet,
        ArchivedPackageViewSet,
    ]
    menu_order = get_menu_order("upload")


register_snippet(UploadViewSetGroup)


class UploadReportsViewSetGroup(SnippetViewSetGroup):
    menu_icon = "folder"
    menu_label = _("Error management")
    items = [
        # os itens a seguir possibilitam que na página Package.inspect
        # funcionem os links para os relatórios
        XMLErrorViewSet,
        XMLErrorReportViewSet,
        XMLInfoReportViewSet,
        ValidationViewSet,
        ValidationReportViewSet,
        UploadValidatorViewSet,
    ]
    menu_order = get_menu_order("upload-error")


register_snippet(UploadReportsViewSetGroup)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("upload/", include("upload.urls", namespace="upload")),
    ]
