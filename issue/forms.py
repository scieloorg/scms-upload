from wagtail.admin.forms import WagtailAdminModelForm

from core.forms import CoreAdminModelForm


class IssueForm(CoreAdminModelForm):
    pass


class TOCForm(CoreAdminModelForm):
    def save_all(self, user):
        obj = super().save_all(user)
        for position, item in enumerate(obj.issue_sections.all()):
            item.position = position
            item.save()
        self.save()
        return obj
