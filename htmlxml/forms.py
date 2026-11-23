from django import forms
from django.utils.translation import gettext_lazy as _
from wagtail.admin.widgets import AdminDateInput

from htmlxml.permissions import managed_collections


def _split_acrons(value):
    return sorted({v.strip() for v in (value or "").replace(";", ",").split(",") if v.strip()})


class Html2xmlReviewRequestForm(forms.Form):
    """
    Solicitação de revisão das conversões HTML -> XML de um escopo,
    feita pelo gestor da coleção (só as coleções que gerencia) ou por um
    administrador.
    """

    collection_acron_list = forms.MultipleChoiceField(
        label=_("Collections"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    journal_acron_list = forms.CharField(
        label=_("Journal acronyms"),
        required=False,
        help_text=_("Comma separated. Empty = all journals"),
    )
    updated_from = forms.DateField(
        label=_("Converted from"), required=False, widget=AdminDateInput
    )
    updated_to = forms.DateField(
        label=_("Converted until"),
        required=False,
        widget=AdminDateInput,
        help_text=_("Inclusive. Empty = until now"),
    )
    only_not_reviewed = forms.BooleanField(
        label=_("Only conversions not reviewed yet"),
        required=False,
        help_text=_(
            "New conversions are reviewed automatically; use this to review the "
            "older ones without reviewing again the ones already reviewed"
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        collections = managed_collections(user)
        if collections is None:
            from collection.models import Collection

            collections = Collection.objects.order_by("acron")
            self.fields["collection_acron_list"].help_text = _("None selected = all collections")
        else:
            self.fields["collection_acron_list"].required = True
        self.fields["collection_acron_list"].choices = [
            (c.acron, f"{c.acron} - {c.name or ''}") for c in collections if c.acron
        ]

    def clean_journal_acron_list(self):
        return _split_acrons(self.cleaned_data.get("journal_acron_list"))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("updated_from"), cleaned.get("updated_to")
        if start and end and start > end:
            self.add_error("updated_to", _("Must be on or after the start date"))
        return cleaned

    def task_kwargs(self):
        data = self.cleaned_data
        return {
            "collection_acron_list": data["collection_acron_list"] or [],
            "journal_acron_list": data["journal_acron_list"] or [],
            "updated_from": data["updated_from"].isoformat() if data.get("updated_from") else None,
            "updated_to": data["updated_to"].isoformat() if data.get("updated_to") else None,
            "only_not_reviewed": bool(data.get("only_not_reviewed")),
        }
