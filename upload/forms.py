import logging
import os

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from core.forms import CoreAdminModelForm
from team.models import CollectionTeamMember, TeamRole
from upload import choices
from upload.authorization import user_can_act_on_package
from upload.permissions import PUBLISH_PACKAGE, REQUEST_CORRECTION
from upload.querysets import (
    correction_assignee_queryset,
    review_assignee_queryset,
    scope_package_queryset,
)


class PackageZipForm(CoreAdminModelForm):
    def save_all(self, user):
        pkg_zip = super().save_all(user)

        pkg_zip.name, _ = os.path.splitext(os.path.basename(pkg_zip.file.name))
        logging.info(pkg_zip.name)
        self.save()

        return pkg_zip


class UploadPackageForm(CoreAdminModelForm):
    pass


class DelegateReviewForm(forms.Form):
    reviewer = forms.ModelChoiceField(
        queryset=None,
        label=_("Reviewer"),
        help_text=_(
            "Choose who will review this document. "
            "This does not change its decision or publication status."
        ),
    )
    instructions = forms.CharField(
        label=_("Instructions"),
        help_text=_("Describe what the reviewer should check in this document."),
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
    )

    def __init__(self, *args, package, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["reviewer"].queryset = review_assignee_queryset(package)
        self.initial["reviewer"] = package.assignee_id


class PackageDecisionForm(CoreAdminModelForm):
    correction_assignee = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        label=_("Responsible for corrections"),
        help_text=_(
            "Choose the original depositor or an active colleague from the same company."
        ),
        required=False,
    )

    force_journal_publication = forms.BooleanField(
        label=_("Força a publicação de journal"),
        required=False,
        help_text=_(
            "Refresh journal data from Core and resend it to the destination website, even if already available."
        ),
    )

    force_issue_publication = forms.BooleanField(
        label=_("Força a publicação de issue"),
        required=False,
        help_text=_(
            "Refresh issue data from Core and resend it to the destination website, even if already available."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["qa_decision"].label = _("Action")
        self.fields["qa_decision"].help_text = _(
            "Choose how to proceed with this document."
        )
        self.fields["qa_decision"].widget.attrs.update(
            {
                "data-upload-decision-target": "action",
                "data-action": "change->upload-decision#refresh",
            }
        )
        self.fields["qa_comment"].label = _("Justification / instructions")
        self.fields["qa_comment"].help_text = _(
            "Describe the corrections needed or justify the publication decision."
        )

        linked_queryset = self.fields["linked"].queryset

        if not self.for_user.is_superuser:
            linked_queryset = scope_package_queryset(
                linked_queryset,
                self.for_user,
            )

        if self.instance.pk:
            linked_queryset = linked_queryset.exclude(pk=self.instance.pk)

        allowed_decisions = set()
        if user_can_act_on_package(self.for_user, REQUEST_CORRECTION, self.instance):
            allowed_decisions.add(choices.PS_PENDING_CORRECTION)
        if user_can_act_on_package(self.for_user, PUBLISH_PACKAGE, self.instance):
            allowed_decisions.update(
                (
                    choices.PS_READY_TO_PREVIEW,
                    choices.PS_READY_TO_PUBLISH,
                    choices.PS_DEPUBLISHED,
                )
            )

        self.fields["qa_decision"].choices = [
            (
                value,
                (
                    _("Republish on QA website")
                    if value == choices.PS_READY_TO_PREVIEW
                    and self.instance.qa_ws_status == choices.PUBLISHED
                    else label
                ),
            )
            for value, label in self.fields["qa_decision"].choices
            if not value or value in allowed_decisions
        ]

        decision = (
            self.data.get(self.add_prefix("qa_decision"))
            if self.is_bound
            else self.initial.get("qa_decision")
        )

        if not self.for_user.is_superuser and decision in (
            choices.PS_READY_TO_PREVIEW,
            choices.PS_READY_TO_PUBLISH,
        ):
            linked_queryset = scope_package_queryset(
                linked_queryset, self.for_user, permission=PUBLISH_PACKAGE
            )

        if decision != choices.PS_PENDING_CORRECTION:
            self.fields["correction_assignee"].disabled = True
        if decision not in (
            choices.PS_READY_TO_PREVIEW,
            choices.PS_READY_TO_PUBLISH,
        ) or not user_can_act_on_package(self.for_user, PUBLISH_PACKAGE, self.instance):
            for field in (
                "linked",
                "order",
                "force_journal_publication",
                "force_issue_publication",
            ):
                self.fields[field].disabled = True

        self.fields["linked"].queryset = linked_queryset.distinct()

        candidates = correction_assignee_queryset(self.instance)
        self.fields["correction_assignee"].queryset = candidates
        responsible_id = (
            self.instance.assignee_id
            if self.instance.status == choices.PS_PENDING_CORRECTION
            else self.instance.creator_id
        )
        if candidates.filter(pk=responsible_id).exists():
            self.initial["correction_assignee"] = responsible_id

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get("qa_decision")

        if self.data.get(self.add_prefix("article")) not in (None, "", "null"):
            self.add_error(
                None,
                _("The document article cannot be changed when recording a decision."),
            )

        if not decision:
            self.add_error("qa_decision", _("Choose an action for this document"))

        if (
            self.data.get(self.add_prefix("qa_decision"))
            == choices.PS_PENDING_QA_DECISION
        ):
            self.add_error(None, _("Use Delegate review to assign a reviewer."))

        if decision == choices.PS_PENDING_CORRECTION:
            if not (cleaned_data.get("qa_comment") or "").strip():
                self.add_error(
                    "qa_comment", _("Justify your decision about the package")
                )
            if not cleaned_data.get("correction_assignee"):
                self.add_error(
                    "correction_assignee", _("Choose who will correct the document")
                )

        return cleaned_data

    def _set_current_user_as_analyst(self, package, user):
        package.analyst = CollectionTeamMember.objects.filter(
            user=user,
            is_active_member=True,
            collection__journalcollection__journal=package.journal,
        ).first()

    def _set_assignee(self, package):
        if package.qa_decision == choices.PS_PENDING_CORRECTION:
            package.assignee = self.cleaned_data["correction_assignee"]
        else:
            package.assignee = None

    def save_all(self, user):
        package = super().save_all(user)

        self._set_current_user_as_analyst(package, user)
        self._set_assignee(package)

        self.save()

        return package


class QAPackageForm(PackageDecisionForm):
    pass


class ReadyToPublishPackageForm(PackageDecisionForm):
    pass


class ValidationResultForm(CoreAdminModelForm):
    pass


class XMLErrorReportForm(CoreAdminModelForm):
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data:
            if cleaned_data.get("xml_producer_ack") not in (False, True):
                self.add_error(
                    "xml_producer_ack",
                    _("Inform if you finish or not the errors review"),
                )

    def save_all(self, user):
        obj = super().save_all(user)
        if obj.package.creator == obj.updated_by:
            obj.package.save()

        if obj.xml_producer_ack:
            obj.conclusion = choices.REPORT_CREATION_DONE
        self.save()

        obj.package.calculate_validation_numbers()
        return obj


class UploadValidatorForm(CoreAdminModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        collections = self.fields["collection"].queryset
        if not self.for_user.is_superuser:
            collections = collections.filter(
                collectionteammember__user=self.for_user,
                collectionteammember__role=TeamRole.MANAGER,
                collectionteammember__is_active_member=True,
            ).distinct()
        self.fields["collection"].queryset = collections
        self.fields["collection"].required = True
        if not self.instance.pk and collections.count() == 1:
            self.initial["collection"] = collections.first().pk

        self.fields["max_xml_warnings_percentage"].help_text = _(
            "Maximum share of XML warnings among all validation results. Enter 0 to 100; 0 allows no warnings."
        )
        self.fields["max_xml_errors_percentage"].help_text = _(
            "Maximum share of XML errors among all validation results. "
            "Enter 0 to 100. Critical issues are handled separately."
        )
        self.fields["max_impossible_to_fix_percentage"].help_text = _(
            "After report review is complete, maximum share of XML findings declared "
            "impossible to correct, among all XML findings. Enter 0 to 100."
        )
        self.fields["decision_for_critical_errors"].help_text = _(
            "Choose whether critical issues require corrections or remain available "
            "for analysis. The strict publication policy always requires corrections."
        )
        self.fields["validation_params"].help_text = _(
            "Technical parameters sent to Packtools to check XML content. "
            "Journal data is added automatically. This field is read-only."
        )

    def clean(self):
        cleaned_data = super().clean()
        for field_name in (
            "max_xml_warnings_percentage",
            "max_xml_errors_percentage",
            "max_impossible_to_fix_percentage",
        ):
            value = cleaned_data.get(field_name)
            if value is not None and not 0 <= value <= 100:
                self.add_error(field_name, _("Value must be from 0 to 100"))

        return cleaned_data
