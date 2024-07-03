from datetime import datetime

from wagtail.admin.forms import WagtailAdminModelForm


class CoreAdminModelForm(WagtailAdminModelForm):
    def save_all(self, user):
        model_with_creator = super().save(commit=False)

        if self.instance.pk is None:
            model_with_creator.creator = user
            model_with_creator.created = datetime.utcnow()
        else:
            model_with_creator.updated_by = user
            model_with_creator.updated = datetime.utcnow()
        self.save()

        return model_with_creator
