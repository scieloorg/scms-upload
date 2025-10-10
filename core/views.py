import logging

from django.http import HttpResponseRedirect

from django.utils.translation import gettext_lazy as _
from wagtail.snippets.views.snippets import CreateView, EditView, SnippetViewSet
from wagtail.admin import messages


class CommonControlFieldCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class CommonControlFieldViewSet(SnippetViewSet):
    """
    Mixin para adicionar tracking de usuário em qualquer SnippetViewSet
    Compatível com Wagtail 6.4.2
    """

    class UserTrackingCreateView(CreateView):
        def save_instance(self):
            logging.info(f"User: {self.request.user}")
            instance = self.form.save(commit=False)
            if not instance.pk:
                instance.creator = self.request.user
            instance.updated_by = self.request.user
            instance.save()
            if hasattr(self.form, "save_m2m"):
                self.form.save_m2m()
            # self.log_action('wagtail.create')
            return instance

    class UserTrackingEditView(EditView):
        def save_instance(self):
            logging.info(f"User: {self.request.user}")
            instance = self.form.save(commit=False)
            instance.updated_by = self.request.user
            instance.save()
            if hasattr(self.form, "save_m2m"):
                self.form.save_m2m()
            # self.log_action('wagtail.edit')
            return instance

    # Define as views customizadas
    add_view_class = UserTrackingCreateView
    edit_view_class = UserTrackingEditView
