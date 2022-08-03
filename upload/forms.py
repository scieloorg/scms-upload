from wagtail.admin.forms import WagtailAdminModelForm


class UploadPackageForm(WagtailAdminModelForm):

    def save_all(self, user):
        upload_package = super().save(commit=False)
        
        if self.instance.pk is None:
            upload_package.creator = user
        
        self.save()

        return upload_package
