from core.forms import CoreAdminModelForm


class ProcAdminModelForm(CoreAdminModelForm):
    def save_all(self, user):
        s = super().save(commit=False)
        s.set_status()
        s.save()
        return s
