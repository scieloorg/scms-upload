import logging

from django import forms
from django.utils.translation import gettext_lazy as _

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

    content_type = forms.ChoiceField(
        label=_("Items"), choices=CONTENT_TYPE_CHOICES, initial="articles"
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from collection.models import Collection

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

    def task_kwargs(self):
        data = self.cleaned_data
        return {
            "content_type": data["content_type"],
            "collection_acron_list": data["collection_acron_list"] or [],
            "journal_acron_list": data["journal_acron_list"] or [],
            "publication_year": data["publication_year"],
            "issue_folder": data["issue_folder"],
        }
