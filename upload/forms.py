import logging

from django import forms
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from wagtail.admin.forms import WagtailAdminModelForm

from upload import choices


class UploadPackageForm(WagtailAdminModelForm):

    def save_all(self, user):
        upload_package = super().save(commit=False)

        if self.instance.pk is None:
            upload_package.creator = user

        self.save()

        return upload_package


class QAPackageForm(WagtailAdminModelForm):

    def save_all(self, user):
        qa_package = super().save(commit=False)

        if self.instance.pk is not None:
            qa_package.updated_by = user
        else:
            qa_package.creator = user

        if qa_package.qa_decision:
            qa_package.status = qa_package.qa_decision

        if qa_package.analyst:
            qa_package.assignee = qa_package.analyst.user
        self.save()

        return qa_package


class ValidationResultForm(WagtailAdminModelForm):
    def save_all(self, user):
        vr_obj = super().save(commit=False)

        if self.instance.pk is None:
            vr_obj.creator = user

        self.save()

        return vr_obj


class XMLErrorReportForm(WagtailAdminModelForm):
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data:
            if not cleaned_data.get("xml_producer_ack"):
                self.add_error(
                    "xml_producer_ack", _("Inform if you finish or not the errors review")
                )

    def save_all(self, user):
        obj = super().save(commit=False)

        if self.instance.pk is None:
            obj.creator = user

        if obj.package.creator == obj.updated_by:
            obj.package.calculate_xml_error_declaration_numbers()
            obj.package.save()

            if obj.xml_producer_ack:
                obj.conclusion = choices.REPORT_CONCLUSION_DONE
        self.save()
        return obj
