import logging

from django import forms
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from wagtail.admin.forms import WagtailAdminModelForm

from upload import choices


class UploadPackageForm(WagtailAdminModelForm):
    def save(self, commit=True):
        upload_package = super().save(commit=False)
        if upload_package.qa_decision:
            upload_package.status = self.instance.qa_decision
        upload_package.save()
        return upload_package

    def save_all(self, user):
        upload_package = super().save(commit=False)

        if self.instance.pk is None:
            upload_package.creator = user
            upload_package.save()

        self.save()

        return upload_package


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
        if not cleaned_data.get("xml_producer_ack"):
            self.add_error(
                "xml_producer_ack", _("Inform if you finish or not the errors review")
            )

    def save_all(self, user):
        vr_obj = super().save(commit=False)

        if self.instance.pk is None:
            vr_obj.creator = user

        self.save()

        return vr_obj

    def save(self, commit=True):
        report = super().save(commit=False)
        if report.package.creator == report.updated_by:
            report.package.calculate_xml_error_declaration_numbers()
            if report.xml_producer_ack:
                report.conclusion = choices.REPORT_CONCLUSION_DONE
            report.package.save()
        return report


class ValidationResultErrorResolutionForm(forms.Form):
    validation_result_id = forms.IntegerField()
    rationale = forms.CharField(widget=forms.Textarea, required=False)
    action = forms.CharField(widget=forms.Select, required=False)


class ValidationResultErrorResolutionOpinionForm(forms.Form):
    validation_result_id = forms.IntegerField()
    guidance = forms.CharField(widget=forms.Textarea, required=False)
    opinion = forms.CharField(widget=forms.Select, required=False)
