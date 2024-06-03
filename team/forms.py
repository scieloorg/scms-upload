from wagtail.admin.forms import WagtailAdminModelForm


class CollectionTeamMemberModelForm(WagtailAdminModelForm):
    def save_all(self, user):
        member = super().save(commit=False)

        if self.instance.pk is not None:
            member.updated_by = user
        else:
            member.creator = user

        self.save()

        return member
