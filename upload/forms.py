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
        qa_package = super().save_all(user)

        if not qa_package.analyst:
            qa_package.analyst = CollectionTeamMember.objects.get(user=user)
        if qa_package.analyst:
            qa_package.assignee = qa_package.analyst.user

        self.save()

        return qa_package


class ApprovedPackageForm(CoreAdminModelForm):
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data:
            qa_decision = cleaned_data.get("qa_decision")
            qa_comment = cleaned_data.get("qa_comment")
            if qa_decision == choices.PS_PENDING_CORRECTION and not qa_comment.strip():
                self.add_error(
                    "qa_comment",
                    _(
                        "Justify your decision about the package"
                    ),
                )
            # manter simples, versão sem possibilidade de agendamento
            # scheduled_release_date = cleaned_data.get("scheduled_release_date")
            # if qa_decision == choices.PS_SCHEDULED_PUBLICATION and not scheduled_release_date:
            #     self.add_error(
            #         "scheduled_release_date",
            #         _(
            #             "Inform the date to make article public"
            #         ),
            #     )

    def save_all(self, user):
        qa_package = super().save_all(user)
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
