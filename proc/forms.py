import logging

from core.forms import CoreAdminModelForm


class ProcAdminModelForm(CoreAdminModelForm):
    def save_all(self, user):
        s = super().save_all(user)
        s.set_status()
        self.save()
        return s


class IssueProcAdminModelForm(ProcAdminModelForm):
    def save_all(self, user):
        s = super().save_all(user)
        if not s.issue_folder and s.issue:
            s.issue_folder = s.issue.issue_folder
        self.save()
        return s
