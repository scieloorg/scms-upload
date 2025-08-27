import logging

from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.http import HttpResponseRedirect
from wagtail_modeladmin.views import CreateView, InspectView


class CollectionTeamMemberCreateView(CreateView):
    def form_valid(self, form):
        form.save_all(self.request.user)
        messages.success(
            self.request,
            _("Member has been successfully created"),
        )
        return HttpResponseRedirect(self.get_success_url())
