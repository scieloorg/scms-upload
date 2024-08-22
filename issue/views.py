from django.http import HttpResponseRedirect
from wagtail.contrib.modeladmin.views import CreateView, EditView


class IssueCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class TOCEditView(EditView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())
