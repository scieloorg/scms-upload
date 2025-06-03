from wagtail.admin.forms import WagtailAdminModelForm
from core.forms import CoreAdminModelForm


class OfficialJournalForm(WagtailAdminModelForm):
    def save_all(self, user):
        journal = super().save(commit=False)

        if self.instance.pk is None:
            journal.creator = user

        self.save()

        return journal
