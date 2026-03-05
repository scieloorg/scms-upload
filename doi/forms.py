from wagtail.admin.forms import WagtailAdminModelForm

from core.forms import CoreAdminModelForm


class DOIWithLangForm(WagtailAdminModelForm):
    def save_all(self, user):
        doi_with_lang = super().save(commit=False)
        doi_with_lang.creator = user

        self.save()

        return doi_with_lang


class CrossrefConfigurationForm(CoreAdminModelForm):
    pass

