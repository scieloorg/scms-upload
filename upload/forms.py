import logging
import os

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from core.forms import CoreAdminModelForm
from core.users.scoped_queryset import scope_by_membership
from team.authorization import get_user_permission_journal_ids
from team.models import CollectionTeamMember
from upload import choices
from upload.authorization import user_can_act_on_package
from upload.permissions import ASSIGN_PACKAGE, PUBLISH_PACKAGE, REQUEST_CORRECTION
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


class PackageDecisionForm(CoreAdminModelForm):
    reviewer = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        label=_("Reviewer"),
        help_text=_("Choose who will review this document."),
        required=False,
    )

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
            "Describe the corrections needed or provide instructions for the reviewer."
        )

        article_queryset = self.fields["article"].queryset
        linked_queryset = self.fields["linked"].queryset

        if not self.for_user.is_superuser:
            article_queryset = scope_by_membership(
                self.for_user,
                article_queryset,
                journal_field="journal",
            )
            linked_queryset = scope_package_queryset(
                linked_queryset,
                self.for_user,
            )

        if self.instance.pk:
            linked_queryset = linked_queryset.exclude(pk=self.instance.pk)

        allowed_decisions = set()
        if user_can_act_on_package(self.for_user, REQUEST_CORRECTION, self.instance):
            allowed_decisions.add(choices.PS_PENDING_CORRECTION)
        if user_can_act_on_package(self.for_user, ASSIGN_PACKAGE, self.instance):
            allowed_decisions.add(choices.PS_PENDING_QA_DECISION)
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
                _("Republish on QA website")
                if value == choices.PS_READY_TO_PREVIEW
                and self.instance.qa_ws_status == choices.PUBLISHED
                else label,
            )
            for value, label in self.fields["qa_decision"].choices
            if not value or value in allowed_decisions
        ]

        reviewers = review_assignee_queryset(self.instance)
        self.fields["reviewer"].queryset = reviewers
        if self.instance.qa_decision == choices.PS_PENDING_QA_DECISION:
            self.initial["reviewer"] = self.instance.assignee_id
        elif self.instance.analyst_id:
            self.initial["reviewer"] = self.instance.analyst.user_id

        decision = (
            self.data.get(self.add_prefix("qa_decision"))
            if self.is_bound
            else self.initial.get("qa_decision")
        )
        if decision != choices.PS_PENDING_QA_DECISION:
            self.initial["reviewer"] = None

        if not self.for_user.is_superuser and decision in (
            choices.PS_READY_TO_PREVIEW,
            choices.PS_READY_TO_PUBLISH,
        ):
            journal_ids = get_user_permission_journal_ids(
                self.for_user, "upload", PUBLISH_PACKAGE
            )
            article_queryset = article_queryset.filter(journal_id__in=journal_ids)
            linked_queryset = scope_package_queryset(
                linked_queryset, self.for_user, permission=PUBLISH_PACKAGE
            )

        if decision != choices.PS_PENDING_QA_DECISION or not user_can_act_on_package(
            self.for_user, ASSIGN_PACKAGE, self.instance
        ):
            self.fields["reviewer"].disabled = True
        if decision != choices.PS_PENDING_CORRECTION:
            self.fields["correction_assignee"].disabled = True
        if decision not in (
            choices.PS_READY_TO_PREVIEW,
            choices.PS_READY_TO_PUBLISH,
        ) or not user_can_act_on_package(self.for_user, PUBLISH_PACKAGE, self.instance):
            for field in (
                "article",
                "linked",
                "order",
                "force_journal_publication",
                "force_issue_publication",
            ):
                self.fields[field].disabled = True

        self.fields["article"].queryset = article_queryset.distinct()
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
        if not decision:
            self.add_error("qa_decision", _("Choose an action for this document"))

        if decision == choices.PS_PENDING_QA_DECISION and not cleaned_data.get(
            "reviewer"
        ):
            self.add_error("reviewer", _("Choose who will review this document."))

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
        if package.qa_decision == choices.PS_PENDING_QA_DECISION:
            return

        package.analyst = CollectionTeamMember.objects.filter(
            user=user,
            is_active_member=True,
            collection__journalcollection__journal=package.journal,
        ).first()

    def _set_assignee(self, package):
        if package.qa_decision == choices.PS_PENDING_CORRECTION:
            package.assignee = self.cleaned_data["correction_assignee"]
        elif package.qa_decision == choices.PS_PENDING_QA_DECISION:
            package.assignee = self.cleaned_data["reviewer"]
            package.analyst = CollectionTeamMember.objects.filter(
                user=package.assignee,
                is_active_member=True,
                collection__journalcollection__journal=package.journal,
            ).first()
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
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data:
            max_x = cleaned_data.get("max_xml_errors_percentage")
            if not max_x or not (0 <= max_x <= 100):
                self.add_error(
                    "max_xml_errors_percentage", _("Value must be from 0 to 100")
                )

            max_x = cleaned_data.get("max_impossible_to_fix_percentage")
            if not max_x or not (0 <= max_x <= 100):
                self.add_error(
                    "max_impossible_to_fix_percentage", _("Value must be from 0 to 100")
                )
