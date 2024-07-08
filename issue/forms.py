from wagtail.admin.forms import WagtailAdminModelForm
from core.forms import CoreAdminModelForm


class IssueForm(WagtailAdminModelForm):
    def save_all(self, user):
        issue = super().save(commit=False)

        if self.instance.pk is None:
            issue.creator = user

        self.save()

        return issue


class TOCForm(CoreAdminModelForm):
    def save_all(self, user):
        obj = super().save(commit=False)
        for position, item in enumerate(obj.issue_sections.all()):
            item.position = position
            item.save()
        self.save()
        return obj
