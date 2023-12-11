from wagtail.admin.forms import WagtailAdminModelForm


class ProcAdminModelForm(WagtailAdminModelForm):
    def save_all(self, user):
        s = super().save(commit=False)

        if self.instance.pk is None:
            s.creator = user

        self.save()

        return s
