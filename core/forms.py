from wagtail.admin.forms import WagtailAdminModelForm


class CoreAdminModelForm(WagtailAdminModelForm):

    def save_all(self, user):
        model_with_creator = super().save(commit=False)
        model_with_creator.creator = user
        self.save()

        return model_with_creator
