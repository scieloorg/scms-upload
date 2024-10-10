import logging

from django.http import HttpResponseRedirect
from wagtail.contrib.modeladmin.views import CreateView, EditView


class ProcCreateView(CreateView):
    def form_valid(self, form):
        logging.info(f"ProcCreateView.user {self.request.user}")
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class ProcEditView(EditView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class CoreCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())
