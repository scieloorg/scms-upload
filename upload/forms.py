from django import forms
from wagtail.admin.forms import WagtailAdminModelForm


class UploadPackageForm(WagtailAdminModelForm):

    def save_all(self, user, article, issue):
        upload_package = super().save(commit=False)
        
        if self.instance.pk is None:
            upload_package.creator = user

        if article is not None:
            upload_package.article = article

        if issue is not None:
            upload_package.issue = issue
        
        self.save()

        return upload_package


class ValidationResultForm(WagtailAdminModelForm):

    def save_all(self, user):
        vr_obj = super().save(commit=False)
        
        if self.instance.pk is None:
            vr_obj.creator = user        
        
        self.save()

        return vr_obj


class ValidationResultErrorResolutionForm(forms.Form):
    validation_result_id = forms.IntegerField()
    rationale = forms.CharField(widget=forms.Textarea, required=False)
    action = forms.CharField(widget=forms.Select, required=False)


class ValidationResultErrorResolutionOpinionForm(forms.Form):
    validation_result_id = forms.IntegerField()
    guidance = forms.CharField(widget=forms.Textarea, required=False)
    opinion = forms.CharField(widget=forms.Select, required=False)
