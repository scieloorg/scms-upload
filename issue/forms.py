from core.forms import CoreAdminModelForm
from core.users.scoped_queryset import scope_by_membership


class IssueForm(CoreAdminModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.for_user or not self.for_user.is_superuser:
            self.fields["journal"].queryset = scope_by_membership(
                self.for_user,
                self.fields["journal"].queryset,
                journal_field="pk",
            )


class TOCForm(CoreAdminModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "issue" in self.fields and (
            not self.for_user or not self.for_user.is_superuser
        ):
            self.fields["issue"].queryset = scope_by_membership(
                self.for_user,
                self.fields["issue"].queryset,
                journal_field="journal",
            )

    def save_all(self, user):
        obj = super().save_all(user)
        for position, item in enumerate(obj.issue_sections.all()):
            item.position = position
            item.save()
        self.save()
        return obj
