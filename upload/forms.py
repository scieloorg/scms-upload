from django import forms
from wagtail.admin.forms import WagtailAdminModelForm


class UploadPackageForm(WagtailAdminModelForm):

    def save_all(self, user):
        upload_package = super().save(commit=False)
        
        if self.instance.pk is None:
            upload_package.creator = user
        
        self.save()

        return upload_package


class ValidationErrorResolutionForm(forms.Form):
    validation_error_id = forms.IntegerField()
    comment = forms.CharField(widget=forms.Textarea, required=False)
    action = forms.CharField(widget=forms.Select, required=False)


class ValidationErrorResolutionOpinionForm(forms.Form):
    validation_error_id = forms.IntegerField()
    comment = forms.CharField(widget=forms.Textarea, required=False)
    opinion = forms.CharField(widget=forms.Select, required=False)
