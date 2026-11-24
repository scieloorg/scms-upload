from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic.edit import FormView
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin

from htmlxml.forms import Html2xmlReprocessForm, Html2xmlReviewRequestForm, Html2xmlTicketCreateForm
from htmlxml.permissions import can_review, managed_collection_ids, managed_collections


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


class _ReviewerFormView(WagtailAdminTemplateMixin, FormView):
    """Formulário do admin para superusuários e gestores de coleção."""

    template_name = "wagtailadmin/generic/form.html"
    header_icon = "warning"
    submit_button_label = _("Confirm")

    def dispatch(self, request, *args, **kwargs):
        if not can_review(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    @property
    def list_url(self):
        return reverse("wagtailsnippets_htmlxml_html2xmlticket:list")

    def get_breadcrumbs_items(self):
        return self.breadcrumbs_items + [
            {"url": self.list_url, "label": _("HTML to XML issues")},
            {"url": "", "label": self.get_page_title()},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            action_url=self.request.get_full_path(),
            submit_button_label=self.submit_button_label,
            submit_button_active_label=_("Saving…"),
            media=context["form"].media,
        )
        return context


class CreateHtml2xmlTicketView(_ReviewerFormView):
    """
    Cria o registro tipo issue de um tipo de problema (``?category=<id>``),
    com descrição e artigos afetados gerados a partir das ocorrências. Se
    já existe um registro aberto para o tipo de problema, vai para ele.
    """

    form_class = Html2xmlTicketCreateForm
    page_title = _("Create HTML to XML issue")
    submit_button_label = _("Create issue")

    def dispatch(self, request, *args, **kwargs):
        from htmlxml.models import Html2xmlIssueCategory, Html2xmlTicket

        if not can_review(request.user):
            raise PermissionDenied
        self.category = get_object_or_404(Html2xmlIssueCategory, pk=request.GET.get("category"))
        existing = (
            Html2xmlTicket.objects.filter(categories=self.category)
            .exclude(status=Html2xmlTicket.STATUS_CLOSED)
            .first()
        )
        if existing:
            return HttpResponseRedirect(
                reverse("wagtailsnippets_htmlxml_html2xmlticket:edit", args=[existing.pk])
            )
        return super().dispatch(request, *args, **kwargs)

    def get_page_subtitle(self):
        return str(self.category)

    def get_initial(self):
        from htmlxml.tickets import ticket_title

        return {"title": ticket_title([self.category])}

    def form_valid(self, form):
        from htmlxml.tickets import create_ticket

        ticket = create_ticket([self.category], user=self.request.user, title=form.cleaned_data["title"])
        messages.success(
            self.request,
            _("Issue created with {} affected articles. Review the description and open it on GitHub.").format(
                ticket.affected()
            ),
        )
        return HttpResponseRedirect(reverse("wagtailsnippets_htmlxml_html2xmlticket:edit", args=[ticket.pk]))


class ReprocessHtml2xmlTicketView(_ReviewerFormView):
    """
    Marca para reprocessamento os artigos afetados por um registro tipo
    issue (o gestor: só os das coleções que gerencia) e o marca como
    resolvido. Roda em segundo plano (``task_reprocess_html2xml``).
    """

    form_class = Html2xmlReprocessForm
    page_title = _("Reprocess affected articles")
    submit_button_label = _("Reprocess")

    def dispatch(self, request, *args, **kwargs):
        from htmlxml.models import Html2xmlTicket

        self.ticket = get_object_or_404(Html2xmlTicket, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_page_subtitle(self):
        return str(self.ticket)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        collections = managed_collections(self.request.user)
        scope = (
            _("all collections")
            if collections is None
            else ", ".join(c.acron for c in collections)
        )
        form.fields["confirm"].label = _(
            "Mark for reprocessing the {} affected articles ({}) of {}"
        ).format(self.ticket.affected(), scope, self.ticket)
        return form

    def form_valid(self, form):
        from htmlxml.models import Html2xmlTicket
        from htmlxml.tasks import task_reprocess_html2xml

        if self.ticket.status == Html2xmlTicket.STATUS_OPEN:
            self.ticket.status = Html2xmlTicket.STATUS_RESOLVED
            self.ticket.updated_by = self.request.user
            self.ticket.save(update_fields=["status", "updated_by", "updated"])
        task_reprocess_html2xml.delay(
            user_id=self.request.user.id,
            ticket_id=self.ticket.pk,
            collection_ids=managed_collection_ids(self.request.user),
        )
        messages.success(
            self.request,
            _(
                "Reprocessing requested: the affected articles are converted again by the "
                "migration flow. \"Still with the problem\" shows how many keep the problem."
            ),
        )
        return HttpResponseRedirect(self.list_url)
