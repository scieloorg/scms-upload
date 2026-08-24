import logging
import os

from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import CoreAdminModelForm
from core.users.scoped_queryset import scope_by_membership
from team.models import CollectionTeamMember
from upload import choices
from upload.querysets import scope_package_queryset


def _infer_quality_review_delegation(cleaned_data, changed_data):
    if (
        "analyst" in changed_data
        and cleaned_data.get("analyst")
        and not cleaned_data.get("qa_decision")
    ):
        cleaned_data["qa_decision"] = choices.PS_PENDING_QA_DECISION


class PackageZipForm(CoreAdminModelForm):
    def save_all(self, user):
        pkg_zip = super().save_all(user)

        pkg_zip.name, ext = os.path.splitext(os.path.basename(pkg_zip.file.name))
        logging.info(pkg_zip.name)
        self.save()

        return pkg_zip


class UploadPackageForm(CoreAdminModelForm):
    pass


class PackageDecisionForm(CoreAdminModelForm):
    force_journal_publication = forms.BooleanField(
        label=_("Força a publicação de journal"),
        required=False,
        help_text=_("Força a publicação de journal"),
    )

    force_issue_publication = forms.BooleanField(
        label=_("Força a publicação de issue"),
        required=False,
        help_text=_("Força a publicação de issue"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        analyst_queryset = CollectionTeamMember.objects.filter(
            is_active_member=True,
            collection__isnull=False,
            user__isnull=False,
        )
        article_queryset = self.fields["article"].queryset
        linked_queryset = self.fields["linked"].queryset

        journal = self.instance.journal
        if not journal and self.instance.issue:
            journal = self.instance.issue.journal
        if not journal and self.instance.article:
            journal = self.instance.article.journal

        if journal:
            analyst_queryset = analyst_queryset.filter(
                collection__in=journal.journal_collections.values_list(
                    "collection",
                    flat=True,
                )
            )

        if not self.for_user or not self.for_user.is_superuser:
            if self.for_user:
                analyst_queryset = analyst_queryset.filter(
                    collection__collectionteammember__user=self.for_user,
                    collection__collectionteammember__is_active_member=True,
                )
            else:
                analyst_queryset = analyst_queryset.none()

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

        self.fields["analyst"].queryset = analyst_queryset.distinct()
        self.fields["article"].queryset = article_queryset.distinct()
        self.fields["linked"].queryset = linked_queryset.distinct()

    def _set_current_user_as_analyst(self, package, user):
        if package.qa_decision == choices.PS_PENDING_QA_DECISION:
            return

        if package.analyst and package.analyst.user == user:
            return

        package.analyst = self.fields["analyst"].queryset.filter(user=user).first()

    def _set_assignee(self, package):
        package.assignee = package.analyst.user if package.analyst else None


class QAPackageForm(PackageDecisionForm):

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data:
            _infer_quality_review_delegation(cleaned_data, self.changed_data)

            analyst = cleaned_data.get("analyst")
            qa_decision = cleaned_data.get("qa_decision")
            if qa_decision == choices.PS_PENDING_QA_DECISION and not analyst:
                self.add_error(
                    "analyst",
                    _("Choose the analyst who will decide about the package"),
                )

            if not qa_decision:
                self.add_error(
                    "qa_decision",
                    _(
                        "Make a decision about the package or choose the analyst who will decide about the package"
                    ),
                )

    def save_all(self, user):
        qa_package = super().save_all(user)

        self._set_current_user_as_analyst(qa_package, user)
        self._set_assignee(qa_package)

        self.save()
        return qa_package


class ReadyToPublishPackageForm(PackageDecisionForm):
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data:
            _infer_quality_review_delegation(cleaned_data, self.changed_data)

            qa_decision = cleaned_data.get("qa_decision")
            qa_comment = cleaned_data.get("qa_comment")
            analyst = cleaned_data.get("analyst")

            if qa_decision == choices.PS_PENDING_CORRECTION and not (
                qa_comment or ""
            ).strip():
                self.add_error(
                    "qa_comment",
                    _("Justify your decision about the package"),
                )

            if qa_decision == choices.PS_PENDING_QA_DECISION and not analyst:
                self.add_error(
                    "analyst",
                    _("Choose the analyst who will decide about the package"),
                )

            if not qa_decision:
                self.add_error(
                    "qa_decision",
                    _(
                        "Make a decision about the package or choose the analyst who will decide about the package"
                    ),
                )

    def save_all(self, user):
        qa_package = super().save_all(user)

        self._set_current_user_as_analyst(qa_package, user)
        self._set_assignee(qa_package)

        self.save()
        return qa_package


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
