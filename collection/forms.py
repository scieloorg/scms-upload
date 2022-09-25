from wagtail.admin.forms import WagtailAdminModelForm


class CollectionForm(WagtailAdminModelForm):

    def save_all(self, user):
        collection = super().save(commit=False)
        collection.creator = user
        self.save()

        return collection
