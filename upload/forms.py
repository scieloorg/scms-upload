import logging
from datetime import datetime

from django import forms
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from core.forms import CoreAdminModelForm
from team.models import CollectionTeamMember
from upload import choices


class UploadPackageForm(CoreAdminModelForm):
    pass


class QAPackageForm(CoreAdminModelForm):
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data:
            analyst = cleaned_data.get("analyst")
            qa_decision = cleaned_data.get("qa_decision")
            if not analyst and not qa_decision:
                self.add_error(
                    "qa_decision",
                    _(
                        "Inform your decision about the package or select an analyst to make the decision about the package"
                    ),
                )

    def save_all(self, user):
        qa_package = super().save(commit=False)
        if qa_package.qa_decision:
            qa_package.status = qa_package.qa_decision
            if qa_package.is_approved:
                if not qa_package.approved_date:
                    qa_package.approved_date = datetime.utcnow()

        if not qa_package.analyst:
            qa_package.analyst = CollectionTeamMember.objects.get(user=user)
        if qa_package.analyst:
            qa_package.assignee = qa_package.analyst.user

        qa_package.approved_date = qa_package.approved_date or datetime.utcnow()

        self.save()

        return qa_package


class ApprovedPackageForm(CoreAdminModelForm):
    pass


class ValidationResultForm(CoreAdminModelForm):
    pass


class XMLErrorReportForm(CoreAdminModelForm):
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data:
            if not cleaned_data.get("xml_producer_ack"):
                self.add_error(
                    "xml_producer_ack",
                    _("Inform if you finish or not the errors review"),
                )

    def save_all(self, user):
        obj = super().save(commit=False)
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
