from django.db.models import Prefetch, Q
from django.templatetags.static import static
from django.urls import include, path
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.ui.tables import TitleColumn
from wagtail.snippets.models import register_snippet
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
from core.views import CommonControlFieldViewSet
from team.models import TeamRole
from upload.bulk_actions.republish import (
    RepublishPublicBulkAction,
    RepublishQABulkAction,
)
from upload.filters import (
    DocumentFilterSet,
    PackageValidationReportFilterSet,
    PackageValidationResultFilterSet,
    SubmissionFilterSet,
    XMLErrorReportFilterSet,
    XMLInfoReportFilterSet,
)
from upload.menu import UploadSectionMenu
from upload.models import (
    Package,
    PackageZip,
    PkgValidationResult,
    QAPackage,
    ReadyToPublishPackage,
    UploadProcResult,
    UploadValidator,
    ValidationReport,
    XMLError,
    XMLErrorReport,
    XMLInfoReport,
    choices,
)
from upload.permission_policies import (
    UploadModelPermissionPolicy,
    ValidationRulePermissionPolicy,
)
from upload.permissions import ACCESS_PACKAGES
from upload.publication_results import PUBLICATION_ATTEMPT_PREFIX
from upload.querysets import (
    document_queue_filter,
    get_scoped_package_queryset,
    scope_package_queryset,
)
from upload.tables import (
    DocumentActionsColumn,
    DocumentTitleColumn,
    DocumentUpdatedColumn,
    PublicationColumn,
    SubmissionActionsColumn,
    SubmissionTitleColumn,
)
from upload.views.decisions import PackageDecisionEditView
from upload.views.documents import (
    PackageAdminInspectView,
    PackageIndexView,
    document_listing_attempts,
)
from upload.views.reports import (
    ValidationReportEditView,
    XMLErrorReportEditView,
    XMLInfoReportEditView,
)
from upload.views.submissions import PackageZipCreateView

MODEL_PERMISSION_ACTIONS = ("add", "change", "delete", "view")


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

    def get_url_name(self, view_name):
        if self.model in (QAPackage, ReadyToPublishPackage) and view_name in (
            "list",
            "list_results",
        ):
            return f"wagtailsnippets_upload_package:{view_name}"
        return super().get_url_name(view_name)

    def get_urlpatterns(self):
        patterns = super().get_urlpatterns()
        if self.model in (QAPackage, ReadyToPublishPackage):
            patterns = [
                pattern
                for pattern in patterns
                if pattern.name not in ("list", "list_results")
            ]
        return patterns


class PackageZipViewSet(BaseUploadViewSet):
    model = PackageZip
    url_prefix = "upload/submissions"
    add_view_class = PackageZipCreateView
    create_template_name = "upload/submissions/create.html"
    copy_view_enabled = False
    index_template_name = "upload/submissions/index.html"
    menu_label = _("Packages")
    menu_name = "submission"
    menu_icon = "upload"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 20

    list_display = (
        SubmissionTitleColumn(
            "name",
            label=_("Name"),
            get_title_id=lambda instance: f"snippet_{instance.pk}_title",
        ),
        "creator",
        "updated",
        SubmissionActionsColumn("actions", label=_("Actions")),
    )
    filterset_class = SubmissionFilterSet
    search_fields = (
        "name",
        "file",
        "creator__username",
        "updated_by__username",
    )

    def get_index_view_kwargs(self, **kwargs):
        return super().get_index_view_kwargs(
            add_item_label=_("Upload package"), **kwargs
        )

    def get_add_view_kwargs(self, **kwargs):
        return super().get_add_view_kwargs(page_title=_("Upload package"), **kwargs)

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
    url_prefix = "upload/documents"
    denied_permission_actions = ("add", "delete")

    index_view_class = PackageIndexView
    index_template_name = "upload/documents/index.html"

    inspect_view_enabled = True
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = "modeladmin/upload/package/inspect.html"
    menu_label = _("Documents")
    menu_name = "documents"
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 20

    list_display = (
        DocumentTitleColumn(
            "__str__",
            label=_("Document"),
            url_name="wagtailsnippets_upload_package:inspect",
            get_title_id=lambda instance: f"snippet_{instance.pk}_title",
            classname="document-title",
        ),
        "work_situation",
        PublicationColumn("publication", label=_("Publication")),
        "assignee",
        DocumentUpdatedColumn("updated", label=_("Updated"), sort_key="updated"),
        DocumentActionsColumn("actions", label=_("Actions")),
    )
    filterset_class = DocumentFilterSet
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
    )

    def get_queryset(self, request):
        qs = (
            super()
            .get_queryset(request)
            .select_related(
                "assignee",
                "article",
            )
            .prefetch_related(
                "article__pages",
                Prefetch(
                    "upload_proc_result",
                    queryset=UploadProcResult.objects.filter(
                        name__startswith=PUBLICATION_ATTEMPT_PREFIX,
                    ).order_by("-created", "-pk"),
                    to_attr="publication_attempts",
                ),
            )
        )
        qs = scope_package_queryset(qs, request.user)
        match = getattr(request, "resolver_match", None)
        if not match or match.url_name in ("list", "list_results"):
            qs = document_listing_attempts(qs, request.GET)
            qs = qs.filter(
                document_queue_filter(
                    request.GET.get("queue", "all"),
                    request.user,
                    status=request.GET.get("status"),
                )
            )
        else:
            package_id = request.GET.get("pkg_zip_id", "")
            if package_id.isdecimal():
                qs = qs.filter(pkg_zip_id=package_id)

        return qs


class QualityAnalysisPackageViewSet(BaseUploadViewSet):
    model = QAPackage
    url_prefix = "upload/quality-review"
    denied_permission_actions = ("delete",)
    edit_view_class = PackageDecisionEditView
    edit_template_name = "upload/decisions/edit.html"
    inspect_view_enabled = True
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = "modeladmin/upload/package/inspect.html"

    def get_queryset(self, request):
        status = [
            choices.PS_VALIDATED_WITH_ERRORS,
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
    url_prefix = "upload/decisions"
    denied_permission_actions = ("delete",)
    edit_view_class = PackageDecisionEditView
    edit_template_name = "upload/decisions/edit.html"
    inspect_view_enabled = True
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = "modeladmin/upload/package/inspect.html"

    def get_queryset(self, request):
        status = [
            choices.PS_PENDING_CORRECTION,
            choices.PS_PENDING_QA_DECISION,
            choices.PS_VALIDATED_WITH_ERRORS,
            choices.PS_READY_TO_PREVIEW,
            choices.PS_PREVIEW,
            choices.PS_READY_TO_PUBLISH,
            choices.PS_PUBLISHED,
        ]
        qs = super().get_queryset(request).filter(status__in=status)

        return scope_package_queryset(qs, request.user)


class XMLErrorReportViewSet(BaseUploadViewSet):
    denied_permission_actions = ("add", "delete")
    model = XMLErrorReport
    package_scope_field = "package"
    edit_view_class = XMLErrorReportEditView
    menu_label = _("XML issues")
    url_prefix = "upload/validation/reports/xml-errors"
    menu_icon = "clipboard-list"
    add_to_settings_menu = False
    list_display = (
        TitleColumn("package", label=_("Document"), url_name="upload:xml_error_report"),
        "category",
        "display_title",
        "creation",
    )
    filterset_class = XMLErrorReportFilterSet
    search_fields = (
        "title",
        "package__name",
        "package__file",
    )


class XMLErrorViewSet(BaseUploadViewSet):
    denied_permission_actions = ("add", "change", "delete")
    inspect_view_enabled = True
    inspect_template_name = "upload/validationresult/inspect.html"
    model = XMLError
    package_scope_field = "report__package"
    menu_label = _("XML results")
    url_prefix = "upload/validation/results/xml-errors"
    menu_icon = "warning"
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
        "advice",
        "report__package__name",
        "report__package__file",
    )


class XMLInfoReportViewSet(BaseUploadViewSet):
    denied_permission_actions = ("add", "delete")
    model = XMLInfoReport
    package_scope_field = "package"
    edit_view_class = XMLInfoReportEditView
    menu_label = _("XML OK")
    url_prefix = "upload/validation/reports/xml-information"
    menu_icon = "info-circle"
    add_to_settings_menu = False
    list_display = (
        TitleColumn("package", label=_("Document"), url_name="upload:xml_info_report"),
        "category",
        "display_title",
        "creation",
    )
    filterset_class = XMLInfoReportFilterSet
    search_fields = (
        "title",
        "package__name",
        "package__file",
    )


class ValidationReportViewSet(BaseUploadViewSet):
    denied_permission_actions = ("add", "delete")
    model = ValidationReport
    package_scope_field = "package"
    edit_view_class = ValidationReportEditView
    menu_label = _("Package validations")
    url_prefix = "upload/validation/reports/package-checks"
    menu_icon = "clipboard-list"
    add_to_settings_menu = False
    list_display = (
        TitleColumn(
            "package", label=_("Document"), url_name="upload:package_validation_report"
        ),
        "category",
        "display_title",
        "creation",
    )
    filterset_class = PackageValidationReportFilterSet
    search_fields = (
        "title",
        "package__name",
        "package__file",
    )


class ValidationViewSet(BaseUploadViewSet):
    denied_permission_actions = ("add", "change", "delete")
    inspect_view_enabled = True
    inspect_template_name = "upload/validationresult/inspect.html"
    model = PkgValidationResult
    package_scope_field = "report__package"
    menu_label = _("Package results")
    url_prefix = "upload/validation/results/package-checks"
    menu_icon = "list-ul"
    add_to_settings_menu = False
    list_display = (
        "subject",
        "status",
        "message",
        "created",
    )
    filterset_class = PackageValidationResultFilterSet
    search_fields = (
        "subject",
        "status",
        "message",
        "report__package__name",
        "report__package__file",
    )


class UploadValidatorViewSet(BaseUploadViewSet):
    model = UploadValidator
    menu_label = _("Validation rules")
    menu_name = "validation-rules"
    url_prefix = "upload/validation/rules"
    menu_icon = "sliders"
    add_to_settings_menu = False
    list_display = (
        "collection",
        "publication_rule",
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

    @property
    def permission_policy(self):
        return ValidationRulePermissionPolicy(self.model)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset

        return queryset.filter(
            collection__collectionteammember__user=request.user,
            collection__collectionteammember__role=TeamRole.MANAGER,
            collection__collectionteammember__is_active_member=True,
        ).distinct()


class UploadTrackingViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Workflow")
    menu_name = "upload-tracking"
    add_to_admin_menu = False
    items = [
        PackageZipViewSet,
        PackageViewSet,
    ]


class ValidationReportsViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Reports")
    menu_name = "upload-reports"
    add_to_admin_menu = False
    items = [
        XMLErrorReportViewSet,
        XMLInfoReportViewSet,
        ValidationReportViewSet,
    ]


class ValidationResultsViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Technical lookup")
    menu_name = "upload-results"
    add_to_admin_menu = False
    items = [XMLErrorViewSet, ValidationViewSet]


class UploadSettingsViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Settings")
    menu_name = "upload-settings"
    add_to_admin_menu = False
    items = [UploadValidatorViewSet]


class UploadViewSetGroup(SnippetViewSetGroup):
    menu_icon = "upload"
    menu_label = "Upload"
    menu_name = "upload"
    items = [
        UploadTrackingViewSetGroup,
        ValidationReportsViewSetGroup,
        ValidationResultsViewSetGroup,
        UploadSettingsViewSetGroup,
    ]
    menu_order = get_menu_order("upload")

    def get_menu_item(self, order=None):
        item = super().get_menu_item(order=order)
        item.menu = UploadSectionMenu(items=self.get_submenu_items())
        return item


register_snippet(UploadViewSetGroup)
for document_viewset in (
    QualityAnalysisPackageViewSet,
    ReadyToPublishPackageViewSet,
):
    document_viewset.add_to_admin_menu = False
    register_snippet(document_viewset)


@hooks.register("register_admin_urls")
def register_upload_urls():
    return [path("upload/", include("upload.urls", namespace="upload"))]


@hooks.register("insert_global_admin_css")
def upload_menu_css():
    return format_html(
        '<link rel="stylesheet" href="{}">', static("upload/css/menu.css")
    )
