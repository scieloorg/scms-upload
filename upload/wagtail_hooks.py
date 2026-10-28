import logging

from django.contrib.admin.utils import quote
from django.db.models import Prefetch, Q
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import include, path, re_path
from django.utils.html import format_html
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
from core.views import CommonControlFieldViewSet
from team.models import TeamRole
from upload.admin_buttons import get_package_action_buttons
from upload.bulk_actions.republish import (
    RepublishPublicBulkAction,
    RepublishQABulkAction,
)
from upload.document_views import PackageAdminInspectView
from upload.document_workflow import QUEUE_LABELS, document_queue_filter
from upload.filters import (
    DocumentFilterSet,
    PackageValidationReportFilterSet,
    SubmissionFilterSet,
    XMLErrorReportFilterSet,
    XMLInfoReportFilterSet,
)
from upload.menu import UploadSectionMenu
from upload.models import (
    ArchivedPackage,
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
    XMLInfo,
    XMLInfoReport,
    choices,
)
from upload.permission_policies import (
    UploadModelPermissionPolicy,
    ValidationRulePermissionPolicy,
)
from upload.permissions import ACCESS_PACKAGES
from upload.publication_status import PUBLICATION_ATTEMPT_PREFIX
from upload.querysets import get_scoped_package_queryset, scope_package_queryset
from upload.tables import (
    DocumentActionsColumn,
    DocumentTitleColumn,
    DocumentUpdatedColumn,
    PublicationColumn,
    SubmissionActionsColumn,
)
from upload.views import (
    PackageZipCreateView,
    QAPackageEditView,
    ReadyToPublishPackageEditView,
    ValidationReportEditView,
    XMLErrorReportEditView,
    XMLInfoReportEditView,
    redirect_upload_url,
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


class DocumentWorkflowIndexView(SnippetIndexView):
    def get(self, request, *args, **kwargs):
        response = redirect("wagtailsnippets_upload_package:list")
        if self.model is ArchivedPackage:
            response["Location"] += "?queue=archived"

        return response


class InspectFirstPackageIndexView(PackageActionIndexView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base = scope_package_queryset(Package.objects.all(), self.request.user)
        base = DocumentFilterSet(
            self.request.GET, queryset=base, request=self.request
        ).qs
        package_id = self.request.GET.get("pkg_zip_id", "")
        if package_id.isdecimal():
            base = base.filter(pkg_zip_id=package_id)
        params = self.request.GET.copy()
        params.pop("p", None)
        params.pop("queue", None)
        selected = self.request.GET.get("queue", "all")
        context["document_queues"] = []
        for key, label in QUEUE_LABELS:
            params["queue"] = key
            context["document_queues"].append(
                {
                    "label": label,
                    "url": "?" + params.urlencode(),
                    "selected": key == selected
                    or (key == "all" and selected not in dict(QUEUE_LABELS)),
                    "count": base.filter(
                        document_queue_filter(
                            key,
                            self.request.user,
                            status=self.request.GET.get("status"),
                        )
                    ).count(),
                }
            )
        pkg_zip_id = self.request.GET.get("pkg_zip_id", "")
        if pkg_zip_id.isdecimal():
            pending_zip = PackageZip.objects.filter(
                pk=pkg_zip_id,
                creator=self.request.user,
                packages__isnull=True,
            ).exists()
            if pending_zip:
                context["no_results_message"] = _(
                    "Documents from this ZIP are not available yet. "
                    "Processing runs in the background. Refresh shortly."
                )

        return context

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
        if self.model in (QAPackage, ReadyToPublishPackage):
            view_kwargs["index_url_name"] = "wagtailsnippets_upload_package:list"
        return view_kwargs


class PackageZipViewSet(BaseUploadViewSet):
    model = PackageZip
    url_prefix = "upload/submissions"
    add_view_class = PackageZipCreateView
    copy_view_enabled = False
    index_template_name = "upload/submissions/index.html"
    menu_label = _("Packages")
    menu_name = "submission"
    menu_icon = "upload"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 20

    list_display = (
        "name",
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

    index_view_class = InspectFirstPackageIndexView
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
        params = {}
        try:
            params["pkg_zip_id"] = request.GET["pkg_zip_id"]
        except KeyError:
            logging.info(request.GET)

        qs = (
            super()
            .get_queryset(request)
            .filter(**params)
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
            qs = qs.filter(
                document_queue_filter(
                    request.GET.get("queue", "all"),
                    request.user,
                    status=request.GET.get("status"),
                )
            )
        return qs


class QualityAnalysisPackageViewSet(BaseUploadViewSet):
    model = QAPackage
    url_prefix = "upload/quality-review"
    denied_permission_actions = ("delete",)
    index_view_class = DocumentWorkflowIndexView
    menu_label = _("Quality review")
    menu_name = "quality-review"
    menu_icon = "search"
    menu_order = 200
    edit_view_class = QAPackageEditView
    edit_template_name = "upload/decisions/edit.html"
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
    index_view_class = DocumentWorkflowIndexView
    denied_permission_actions = ("delete",)
    menu_label = _("Decisions")
    menu_name = "publication"
    menu_icon = "tasks"
    menu_order = 200
    edit_view_class = ReadyToPublishPackageEditView
    edit_template_name = "upload/decisions/edit.html"
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
    model = XMLErrorReport
    package_scope_field = "package"
    edit_view_class = XMLErrorReportEditView
    menu_label = _("XML errors")
    url_prefix = "upload/validation/reports/xml-errors"
    menu_icon = "clipboard-list"
    add_to_settings_menu = False
    list_display = (
        "package",
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
    model = XMLError
    package_scope_field = "report__package"
    menu_label = _("XML errors")
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
    menu_label = _("XML information")
    url_prefix = "upload/validation/reports/xml-information"
    menu_icon = "info-circle"
    add_to_settings_menu = False
    list_display = (
        "package",
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
    menu_label = _("Package checks")
    url_prefix = "upload/validation/reports/package-checks"
    menu_icon = "clipboard-list"
    add_to_settings_menu = False
    list_display = (
        "package",
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
    model = PkgValidationResult
    package_scope_field = "report__package"
    menu_label = _("Package checks")
    url_prefix = "upload/validation/results/package-checks"
    menu_icon = "list-ul"
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


class ArchivedPackageViewSet(BaseUploadViewSet):
    model = ArchivedPackage
    url_prefix = "upload/archive"
    index_view_class = DocumentWorkflowIndexView
    denied_permission_actions = ("delete",)
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = "modeladmin/upload/package/inspect.html"
    menu_label = _("Archived")
    menu_name = "archive"
    menu_icon = "history"
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
    )

    def get_queryset(self, request):
        qs = (
            super()
            .get_queryset(request)
            .exclude(status__in=(*choices.PS_WIP, choices.PS_PENDING_CORRECTION))
        )

        return scope_package_queryset(qs, request.user)


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
    menu_label = _("Individual results")
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
    ArchivedPackageViewSet,
):
    document_viewset.add_to_admin_menu = False
    register_snippet(document_viewset)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        re_path(
            r"^snippets/upload/(?P<model_name>xmlerrorreport|xmlinforeport|"
            r"validationreport|xmlerror|pkgvalidationresult|uploadvalidator|"
            r"packagezip|package|qapackage|readytopublishpackage|archivedpackage)/"
            r"(?P<subpath>.*)$",
            redirect_upload_url,
        ),
        path("upload/", include("upload.urls", namespace="upload")),
    ]


@hooks.register("insert_global_admin_css")
def upload_menu_css():
    return format_html(
        '<link rel="stylesheet" href="{}">', static("upload/css/menu.css")
    )
