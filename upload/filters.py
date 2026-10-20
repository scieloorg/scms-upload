from django.utils.translation import gettext_lazy as _
from django_filters import (
    BooleanFilter,
    CharFilter,
    ChoiceFilter,
    DateFromToRangeFilter,
)
from wagtail.admin.filters import DateRangePickerWidget, WagtailFilterSet
from wagtail.admin.widgets import BooleanRadioSelect

from upload import choices
from upload.models import (
    Package,
    PackageZip,
    ValidationReport,
    XMLErrorReport,
    XMLInfoReport,
)

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


class DocumentFilterSet(WagtailFilterSet):
    package = CharFilter(
        field_name="pkg_zip__name",
        lookup_expr="icontains",
        label=_("Package"),
    )

    class Meta:
        model = Package
        fields = ("package", "blocking_errors", "critical_errors", "category", "status")


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
