from django.utils.translation import gettext_lazy as _
from django_filters import (
    BooleanFilter,
    CharFilter,
    ChoiceFilter,
    DateFromToRangeFilter,
    ModelChoiceFilter,
)
from wagtail.admin.filters import DateRangePickerWidget, WagtailFilterSet
from wagtail.admin.widgets import BooleanRadioSelect

from upload import choices
from upload.document_workflow import WORK_STATUS_CHOICES
from upload.models import (
    Package,
    PackageZip,
    PkgValidationResult,
    ValidationReport,
    XMLErrorReport,
    XMLInfoReport,
)
from upload.publication_status import PUBLICATION_STATE_LABELS
from upload.querysets import get_scoped_package_queryset

CREATION_UNSPECIFIED = "unspecified"


class ValidationReportFilterSet(WagtailFilterSet):
    creation = ChoiceFilter(
        label=_("Report generation"),
        empty_label=_("All"),
        choices=[
            (value, label)
            for value, label in choices.REPORT_CREATION
            if value != choices.REPORT_CREATION_NONE
        ]
        + [(CREATION_UNSPECIFIED, _("Not specified"))],
        method="filter_creation",
    )

    class Meta:
        fields = ("category", "creation")

    def filter_creation(self, queryset, name, value):
        if value == CREATION_UNSPECIFIED:
            value = choices.REPORT_CREATION_NONE

        return queryset.filter(**{name: value})


class XMLErrorReportFilterSet(ValidationReportFilterSet):
    class Meta(ValidationReportFilterSet.Meta):
        model = XMLErrorReport


class XMLInfoReportFilterSet(ValidationReportFilterSet):
    class Meta(ValidationReportFilterSet.Meta):
        model = XMLInfoReport


class PackageValidationReportFilterSet(ValidationReportFilterSet):
    class Meta(ValidationReportFilterSet.Meta):
        model = ValidationReport


def scoped_validation_reports(request):
    if request is None:
        return ValidationReport.objects.none()

    return ValidationReport.objects.filter(
        package__in=get_scoped_package_queryset(request.user)
    ).select_related("package")


class PackageValidationResultFilterSet(WagtailFilterSet):
    document = CharFilter(
        field_name="report__package__name",
        lookup_expr="icontains",
        label=_("Document"),
    )

    report = ModelChoiceFilter(
        label=_("Report"),
        queryset=scoped_validation_reports,
        empty_label=_("All"),
    )

    class Meta:
        model = PkgValidationResult
        fields = ("status", "document", "report")


class DocumentFilterSet(WagtailFilterSet):
    package = CharFilter(
        field_name="pkg_zip__name",
        lookup_expr="icontains",
        label=_("Package"),
    )

    status = ChoiceFilter(
        label=_("Work status"),
        choices=WORK_STATUS_CHOICES,
        empty_label=_("All"),
    )
    qa_ws_status = ChoiceFilter(
        label=_("QA"),
        choices=[
            (value, PUBLICATION_STATE_LABELS.get(value, label))
            for value, label in choices.WEBSITE_STATUS
        ],
        empty_label=_("All"),
    )
    public_ws_status = ChoiceFilter(
        label=_("Public"),
        choices=[
            (value, PUBLICATION_STATE_LABELS.get(value, label))
            for value, label in choices.WEBSITE_STATUS
        ],
        empty_label=_("All"),
    )
    blocking_errors = BooleanFilter(
        label=_("Blocking errors"),
        widget=BooleanRadioSelect,
        method="filter_has_errors",
    )
    critical_errors = BooleanFilter(
        label=_("Critical errors"),
        widget=BooleanRadioSelect,
        method="filter_has_errors",
    )

    class Meta:
        model = Package
        fields = (
            "package",
            "status",
            "qa_ws_status",
            "public_ws_status",
            "category",
            "blocking_errors",
            "critical_errors",
        )

    def filter_has_errors(self, queryset, name, value):
        lookup = {f"{name}__gt": 0}
        return queryset.filter(**lookup) if value else queryset.exclude(**lookup)


class SubmissionFilterSet(WagtailFilterSet):
    created = DateFromToRangeFilter(
        label=_("Submission date"),
        widget=DateRangePickerWidget,
    )
    updated = DateFromToRangeFilter(
        label=_("Last update date"),
        widget=DateRangePickerWidget,
    )
    has_documents = BooleanFilter(
        label=_("Contains documents"),
        widget=BooleanRadioSelect,
        method="filter_has_documents",
    )

    class Meta:
        model = PackageZip
        fields = ("creator", "created", "updated", "has_documents")

    def filter_has_documents(self, queryset, name, value):
        return queryset.filter(packages__isnull=not value).distinct()
