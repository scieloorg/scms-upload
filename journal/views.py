from django.http import HttpResponseRedirect
from django.utils.translation import gettext as _
from django.shortcuts import render
from wagtail.contrib.modeladmin.views import CreateView, EditView


# Create your views here.
class JournalTOCCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class JournalTOCEditView(EditView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())
