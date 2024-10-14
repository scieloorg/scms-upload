import logging

from django.urls import include, path
from django.utils.translation import gettext as _
from wagtail import hooks
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)

from config.menu import get_menu_order
from upload.views import (
    ReadyToPublishPackageEditView,
    PackageAdminInspectView,
    QAPackageEditView,
    ValidationReportEditView,
    XMLErrorReportEditView,
    XMLInfoReportEditView,
    PackageZipCreateView,
)

from .button_helper import UploadButtonHelper
from .models import (
    ReadyToPublishPackage,
    Package,
    PkgValidationResult,
    QAPackage,
    UploadValidator,
    ValidationReport,
    XMLError,
    XMLErrorReport,
    XMLInfo,
    XMLInfoReport,
    choices,
    PackageZip,
)
from .permission_helper import UploadPermissionHelper
from team.models import has_permission


class PackageZipAdmin(ModelAdmin):
    model = PackageZip
    # button_helper_class = UploadButtonHelper
    permission_helper_class = UploadPermissionHelper
    create_view_enabled = True
    create_view_class = PackageZipCreateView
    inspect_view_enabled = False
    menu_label = _("Upload")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False
    list_per_page = 20

    list_display = (
        "name",
        "__str__",
        "creator",
        "updated",
    )
    # list_filter = (
    # )
    search_fields = (
        "name",
        "file",
        "creator__username",
        "updated_by__username",
    )

    def get_queryset(self, request):
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        params = {}
        if self.permission_helper.user_can_finish_deposit(request.user, None):
            params = {"creator": request.user}

        return super().get_queryset(request).filter(**params)


class PackageAdmin(ModelAdmin):
    model = Package
    button_helper_class = UploadButtonHelper
    permission_helper_class = UploadPermissionHelper
    create_view_enabled = False
    # create_view_class = PackageCreateView
    inspect_view_enabled = True
    inspect_view_class = PackageAdminInspectView
    menu_label = _("Validation")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False
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
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        params = {}

        try:
            params["pkg_zip__id"] = request.GET["pkg_zip_id"]
        except KeyError:
            logging.info(request.GET)

        if self.permission_helper.user_can_finish_deposit(request.user, None):
            params["creator"] = request.user
            action_required = [
                choices.PS_VALIDATED_WITH_ERRORS,
                choices.PS_PENDING_CORRECTION,
                choices.PS_UNEXPECTED,
                choices.PS_REQUIRED_ERRATUM,
                choices.PS_REQUIRED_UPDATE,
            ]
            waiting_status = [
                choices.PS_ENQUEUED_FOR_VALIDATION,
                choices.PS_PENDING_QA_DECISION,
                choices.PS_READY_TO_PREVIEW,
                choices.PS_PREVIEW,
                choices.PS_READY_TO_PUBLISH,
                choices.PS_PUBLISHED,
            ]

            status = action_required + waiting_status

        else:
            waiting_status = [
                choices.PS_ENQUEUED_FOR_VALIDATION,
                choices.PS_PENDING_CORRECTION,
                choices.PS_UNEXPECTED,
                choices.PS_REQUIRED_ERRATUM,
                choices.PS_REQUIRED_UPDATE,
            ]
            action_required = [
                choices.PS_VALIDATED_WITH_ERRORS,
            ]

            # Ações requeridas no menu QA, neste menu é para consultar
            action_required_qa_menu = [
                choices.PS_PENDING_QA_DECISION,
            ]

            # Ações requeridas no menu Publication, neste menu é para consultar
            action_required_publication_menu = [
                choices.PS_READY_TO_PREVIEW,
                choices.PS_PREVIEW,
                choices.PS_READY_TO_PUBLISH,
                choices.PS_PUBLISHED,
            ]

            status = (
                action_required
                + waiting_status
                + action_required_qa_menu
                + action_required_publication_menu
            )

        return super().get_queryset(request).filter(status__in=status, **params)


class QualityAnalysisPackageAdmin(ModelAdmin):
    model = QAPackage
    button_helper_class = UploadButtonHelper
    permission_helper_class = UploadPermissionHelper
    menu_label = _("Pending decision")
    menu_icon = "folder"
    menu_order = 200
    edit_view_class = QAPackageEditView
    inspect_view_enabled = True
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = "modeladmin/upload/package/inspect.html"
    add_to_settings_menu = False
    exclude_from_explorer = False
    list_per_page = 20

    list_display = (
        "__str__",
        "assignee",
        "analyst",
        "xml_errors_percentage",
        "contested_xml_errors_percentage",
        "declared_impossible_to_fix_percentage",
        "category",
        "status",
        "updated",
        "expiration_date",
    )
    list_filter = ("status", "category")
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
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        """
        Para Analista de Qualidade
        PS_VALIDATED_WITH_ERRORS:
            sem esperar o produtor de XML terminar o depósito,
            revisar os erros, aceitar ou rejeitar pacote
        PS_PENDING_CORRECTION:
            a pedido do produtor de XML,
            revisar os erros, aceitar ou rejeitar pacote
        PS_PENDING_QA_DECISION:
            a pedido do produtor de XML,
            revisar os erros, aceitar ou rejeitar pacote

        Para o produtor de XML, apenas consulta
        """
        status = [
            choices.PS_VALIDATED_WITH_ERRORS,
            choices.PS_PENDING_CORRECTION,
            choices.PS_PENDING_QA_DECISION,
        ]
        params = {}
        if self.permission_helper.user_can_finish_deposit(request.user, None):
            params = {"creator": request.user}

        return super().get_queryset(request).filter(status__in=status, **params)


class ReadyToPublishPackageAdmin(ModelAdmin):
    model = ReadyToPublishPackage

    button_helper_class = UploadButtonHelper
    permission_helper_class = UploadPermissionHelper
    menu_label = _("Publication")
    menu_icon = "folder"
    menu_order = 200
    edit_view_class = ReadyToPublishPackageEditView
    inspect_view_enabled = True
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = "modeladmin/upload/package/inspect.html"
    add_to_settings_menu = False
    exclude_from_explorer = False
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
    list_filter = ("status", "category")
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
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        status = [
            choices.PS_READY_TO_PREVIEW,
            choices.PS_PREVIEW,
            choices.PS_READY_TO_PUBLISH,
            # choices.PS_SCHEDULED_PUBLICATION,
        ]
        params = {}
        if self.permission_helper.user_can_finish_deposit(request.user, None):
            params = {"creator": request.user}

        return super().get_queryset(request).filter(status__in=status, **params)


class XMLErrorReportAdmin(ModelAdmin):
    model = XMLErrorReport
    permission_helper_class = UploadPermissionHelper
    edit_view_class = XMLErrorReportEditView
    # create_view_class = XMLErrorReportCreateView
    inspect_view_enabled = True
    # inspect_view_class = XMLErrorReportAdminInspectView
    menu_label = _("XML Error Reports")
    menu_icon = "error"
    add_to_settings_menu = False
    exclude_from_explorer = False
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

    def get_queryset(self, request):
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        if (
            request.user.is_superuser
            or self.permission_helper.user_can_access_all_packages(request.user, None)
        ):
            return super().get_queryset(request)

        return super().get_queryset(request).filter(package__creator=request.user)


class XMLErrorAdmin(ModelAdmin):
    model = XMLError
    permission_helper_class = UploadPermissionHelper
    # create_view_class = XMLErrorCreateView
    inspect_view_enabled = True
    # inspect_view_class = XMLErrorAdminInspectView
    menu_label = _("XML errors")
    menu_icon = "error"
    add_to_settings_menu = False
    exclude_from_explorer = False
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

    def get_queryset(self, request):
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        if (
            request.user.is_superuser
            or self.permission_helper.user_can_access_all_packages(request.user, None)
        ):
            return super().get_queryset(request)

        return super().get_queryset(request).filter(package__creator=request.user)


class XMLInfoReportAdmin(ModelAdmin):
    model = XMLInfoReport
    permission_helper_class = UploadPermissionHelper
    edit_view_class = XMLInfoReportEditView
    # create_view_class = XMLInfoReportCreateView
    inspect_view_enabled = True
    # inspect_view_class = XMLInfoReportAdminInspectView
    menu_label = _("XML Info Reports")
    menu_icon = "error"
    add_to_settings_menu = False
    exclude_from_explorer = False
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

    def get_queryset(self, request):
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        if (
            request.user.is_superuser
            or self.permission_helper.user_can_access_all_packages(request.user, None)
        ):
            return super().get_queryset(request)

        return super().get_queryset(request).filter(package__creator=request.user)


class XMLInfoAdmin(ModelAdmin):
    model = XMLInfo
    permission_helper_class = UploadPermissionHelper
    # create_view_class = XMLInfoCreateView
    inspect_view_enabled = True
    # inspect_view_class = XMLInfoAdminInspectView
    menu_label = _("XML info")
    menu_icon = "error"
    add_to_settings_menu = False
    exclude_from_explorer = False
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

    def get_queryset(self, request):
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        if (
            request.user.is_superuser
            or self.permission_helper.user_can_access_all_packages(request.user, None)
        ):
            return super().get_queryset(request)

        return super().get_queryset(request).filter(package__creator=request.user)


class ValidationReportAdmin(ModelAdmin):
    model = ValidationReport
    permission_helper_class = UploadPermissionHelper
    # create_view_class = ValidationReportCreateView
    edit_view_class = ValidationReportEditView

    inspect_view_enabled = True
    # inspect_view_class = ValidationReportAdminInspectView
    menu_label = _("Validation Reports")
    menu_icon = "error"
    add_to_settings_menu = False
    exclude_from_explorer = False
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

    def get_queryset(self, request):
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        if (
            request.user.is_superuser
            or self.permission_helper.user_can_access_all_packages(request.user, None)
        ):
            return super().get_queryset(request)

        return super().get_queryset(request).filter(package__creator=request.user)


class ValidationAdmin(ModelAdmin):
    model = PkgValidationResult
    permission_helper_class = UploadPermissionHelper
    # create_view_class = ValidationCreateView
    inspect_view_enabled = True
    # inspect_view_class = ValidationAdminInspectView
    menu_label = _("Validations")
    menu_icon = "error"
    add_to_settings_menu = False
    exclude_from_explorer = False
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

    def get_queryset(self, request):
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        if (
            request.user.is_superuser
            or self.permission_helper.user_can_access_all_packages(request.user, None)
        ):
            return super().get_queryset(request)

        return super().get_queryset(request).filter(package__creator=request.user)


class UploadValidatorAdmin(ModelAdmin):
    model = UploadValidator
    permission_helper_class = UploadPermissionHelper
    # create_view_class = ValidationCreateView
    inspect_view_enabled = False
    # inspect_view_class = ValidationAdminInspectView
    menu_label = _("Upload Validator")
    menu_icon = "folder"
    add_to_settings_menu = False
    exclude_from_explorer = False
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
        if not self.permission_helper.user_can_use_upload_module(request.user, None):
            return super().get_queryset(request).none()
        if (
            request.user.is_superuser
            or self.permission_helper.user_can_access_all_packages(request.user, None)
        ):
            return super().get_queryset(request)

        return super().get_queryset(request).none()


class UploadModelAdminGroup(ModelAdminGroup):
    menu_icon = "folder"
    menu_label = "Upload"
    items = (
        PackageZipAdmin,
        PackageAdmin,
        QualityAnalysisPackageAdmin,
        ReadyToPublishPackageAdmin,
    )
    menu_order = get_menu_order("upload")


modeladmin_register(UploadModelAdminGroup)


class UploadReportsModelAdminGroup(ModelAdminGroup):
    menu_icon = "folder"
    menu_label = _("Error management")
    items = (
        # os itens a seguir possibilitam que na página Package.inspect
        # funcionem os links para os relatórios
        XMLErrorAdmin,
        XMLErrorReportAdmin,
        XMLInfoReportAdmin,
        ValidationAdmin,
        ValidationReportAdmin,
        UploadValidatorAdmin,
    )
    menu_order = get_menu_order("upload-error")

modeladmin_register(UploadReportsModelAdminGroup)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("upload/", include("upload.urls", namespace="upload")),
    ]
