from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic.edit import FormView
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin

from htmlxml.forms import Html2xmlReviewRequestForm
from htmlxml.permissions import can_review


class RequestHtml2xmlReviewView(WagtailAdminTemplateMixin, FormView):
    """
    Formulário em que o gestor da coleção (ou um administrador) solicita a
    revisão das conversões HTML -> XML de um escopo. A revisão roda em
    segundo plano (``task_review_html2xml``) e os resultados aparecem em
    Processing > HTML to XML review.
    """

    form_class = Html2xmlReviewRequestForm
    template_name = "wagtailadmin/generic/form.html"
    page_title = _("Request HTML to XML review")
    header_icon = "warning"

    def dispatch(self, request, *args, **kwargs):
        if not can_review(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    @property
    def list_url(self):
        return reverse("wagtailsnippets_htmlxml_html2xmlproblem:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_breadcrumbs_items(self):
        return self.breadcrumbs_items + [
            {"url": self.list_url, "label": _("HTML to XML review")},
            {"url": "", "label": self.page_title},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            action_url=self.request.path,
            submit_button_label=_("Request review"),
            submit_button_active_label=_("Scheduling…"),
            media=context["form"].media,
        )
        return context

    def form_valid(self, form):
        from htmlxml.tasks import task_review_html2xml

        task_review_html2xml.delay(user_id=self.request.user.id, **form.task_kwargs())
        messages.success(
            self.request,
            _(
                "Review requested. It runs in the background; reload this page "
                "to see the problems found."
            ),
        )
        return HttpResponseRedirect(self.list_url)
