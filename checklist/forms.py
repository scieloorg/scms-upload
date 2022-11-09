from wagtail.admin.forms import WagtailAdminModelForm


class  ManualCheckingForm(WagtailAdminModelForm):

    def save_all(self, user):
        obj = super().save(commit=False)
        
        if self.instance.pk is None:
            obj.creator = user

        for i in self.instance.item.all():
            i.creator = user
      
        self.save()

        return obj


class ItemForm(WagtailAdminModelForm):

    def save_all(self, user):
        obj = super().save(commit=False)
        
        if self.instance.pk is None:
            obj.creator = user
      
        self.save()

        return obj
