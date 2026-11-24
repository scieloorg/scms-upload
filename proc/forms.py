import logging

from datetime import timedelta

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from wagtail.admin.widgets import AdminDateInput

from core.forms import CoreAdminModelForm


class ProcAdminModelForm(CoreAdminModelForm):
    def save_all(self, user):
        s = super().save_all(user)
        s.propagate_reproc_or_todo_status()
        self.save()
        return s


class IssueProcAdminModelForm(ProcAdminModelForm):
    def save_all(self, user):
        s = super().save_all(user)
        if not s.issue_folder and s.issue:
            s.issue_folder = s.issue.issue_folder
        self.save()
        return s


def _split_acrons(value):
    return sorted({v.strip() for v in (value or "").replace(";", ",").split(",") if v.strip()})


class ProblemReportRequestForm(forms.Form):
    """Escopo do relatório de problemas gerado sob demanda (situação atual)."""

    CONTENT_TYPE_CHOICES = [
        ("articles", _("Issues and articles")),
        ("issues", _("Issues")),
        ("journals", _("Journals")),
        ("all", _("Journals, issues and articles")),
    ]

    REPORT_TYPE_CHOICES = [
        ("problems", _("Migration/publication problems (blocked or pending items)")),
        ("html2xml", _("HTML to XML conversion (quality of the converted articles)")),
    ]

    report_type = forms.ChoiceField(
        label=_("Report"),
        choices=REPORT_TYPE_CHOICES,
        initial="problems",
        required=False,
        widget=forms.RadioSelect,
        help_text=_(
            "HTML to XML conversion: analyzes every article converted from HTML in the "
            "period (by conversion date), groups the problems found (failed steps, "
            "lost content, HTML left in the XML, broken links...) by category and shows "
            "whether each one is spread over many journals (likely systematic) or "
            "concentrated in one (likely data)."
        ),
    )
    content_type = forms.ChoiceField(
        label=_("Items"),
        choices=CONTENT_TYPE_CHOICES,
        initial="articles",
        help_text=_("Only for the migration/publication problems report"),
    )
    updated_from = forms.DateField(
        label=_("Items updated from"),
        widget=AdminDateInput,
        help_text=_(
            "Any date is accepted. All items with a problem status (blocked or pending) "
            "updated in the period are analyzed, the most recent first, up to the maximum "
            "number of items below (and within the server memory and time). If it does not "
            "fit, the report is still delivered with the most recent ones and marked as "
            "\"Ready (incomplete)\", showing how many items were left out."
        ),
    )
    updated_to = forms.DateField(
        label=_("Items updated until"),
        required=False,
        widget=AdminDateInput,
        help_text=_("Inclusive. Empty = until now"),
    )
    max_items = forms.IntegerField(
        label=_("Maximum number of items with problems"),
        min_value=1,
        help_text=_(
            "Set according to the server capacity. Above it, the report is still "
            "delivered, with the most recently updated items, and marked as "
            "\"Ready (incomplete)\"."
        ),
    )
    collection_acron_list = forms.MultipleChoiceField(
        label=_("Collections"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=_("None selected = all collections"),
    )
    journal_acron_list = forms.CharField(
        label=_("Journal acronyms"),
        required=False,
        help_text=_("Comma separated. Empty = all journals"),
    )
    publication_year = forms.CharField(label=_("Publication year"), required=False, max_length=4)
    issue_folder = forms.CharField(label=_("Issue folder"), required=False, max_length=23)

    DEFAULT_PERIOD_DAYS = 7

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from collection.models import Collection

        from htmlxml.permissions import managed_collections
        from proc.models import ProblemReport

        self.fields["updated_from"].initial = (
            timezone.localdate() - timedelta(days=self.DEFAULT_PERIOD_DAYS)
        )
        self.fields["max_items"].initial = ProblemReport.DEFAULT_MAX_ITEMS

        # gestor de coleção (não administrador): só o relatório de conversão
        # HTML -> XML e só das coleções que gerencia
        collections = managed_collections(user) if user is not None else None
        self.restricted = collections is not None
        if self.restricted:
            self.fields["report_type"].choices = [
                c for c in self.REPORT_TYPE_CHOICES if c[0] == "html2xml"
            ]
            self.fields["report_type"].initial = "html2xml"
            self.fields["collection_acron_list"].required = True
            self.fields["collection_acron_list"].help_text = ""
            self.fields["collection_acron_list"].choices = [
                (c.acron, f"{c.acron} - {c.name or ''}") for c in collections if c.acron
            ]
            return

        self.fields["collection_acron_list"].choices = [
            (acron, f"{acron} - {name or ''}")
            for acron, name in Collection.objects.order_by("acron").values_list("acron", "name")
            if acron
        ]

    def clean_journal_acron_list(self):
        return _split_acrons(self.cleaned_data.get("journal_acron_list"))

    def clean_publication_year(self):
        value = (self.cleaned_data.get("publication_year") or "").strip()
        if value and not (value.isdigit() and len(value) == 4):
            raise forms.ValidationError(_("Use 4 digits (YYYY)"))
        return value or None

    def clean_issue_folder(self):
        return (self.cleaned_data.get("issue_folder") or "").strip() or None

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("updated_from"), cleaned.get("updated_to")
        if start and end and start > end:
            self.add_error("updated_to", _("Must be on or after the start date"))
        return cleaned

    def task_kwargs(self):
        data = self.cleaned_data
        return {
            "report_type": "html2xml" if self.restricted else (data.get("report_type") or "problems"),
            "content_type": data["content_type"],
            "max_items": data["max_items"],
            "collection_acron_list": data["collection_acron_list"] or [],
            "journal_acron_list": data["journal_acron_list"] or [],
            "publication_year": data["publication_year"],
            "issue_folder": data["issue_folder"],
            "updated_from": data["updated_from"].isoformat() if data.get("updated_from") else None,
            "updated_to": data["updated_to"].isoformat() if data.get("updated_to") else None,
        }
