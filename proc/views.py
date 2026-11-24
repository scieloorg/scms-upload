import logging

from django.http import HttpResponseRedirect
from wagtail_modeladmin.views import CreateView, EditView


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


from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from django.views.generic.edit import FormView
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin

from proc.forms import ProblemReportRequestForm


class GenerateProblemReportView(WagtailAdminTemplateMixin, FormView):
    """
    Gera, sob demanda, o relatório de problemas com a situação atual dos
    ``*Proc`` (sem executar migração). A geração roda no celery
    (``task_generate_problem_report`` sem espera) e o arquivo aparece na
    lista de "Problem reports".
    """

    form_class = ProblemReportRequestForm
    template_name = "wagtailadmin/generic/form.html"
    page_title = _("Generate problem report")
    header_icon = "warning"

    def dispatch(self, request, *args, **kwargs):
        # administradores; gestores de coleção só geram o relatório de
        # conversão HTML -> XML das suas coleções (ver o formulário)
        from htmlxml.permissions import can_review

        if not (request.user.is_active and (request.user.is_superuser or can_review(request.user))):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    @property
    def list_url(self):
        return reverse("wagtailsnippets_proc_problemreport:list")

    def get_breadcrumbs_items(self):
        return self.breadcrumbs_items + [
            {"url": self.list_url, "label": _("Problem reports")},
            {"url": "", "label": self.page_title},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            action_url=self.request.path,
            submit_button_label=_("Generate report"),
            submit_button_active_label=_("Scheduling…"),
            media=context["form"].media,
        )
        return context

    def form_valid(self, form):
        from proc.models import ProblemReport
        from proc.tasks import (
            _problem_report_scope,
            report_item_types,
            task_generate_problem_report,
        )

        kwargs = form.task_kwargs()
        triggered_by = "admin (on demand)"
        # registra já a solicitação para que apareça na lista com o status
        report = ProblemReport.create_request(
            _problem_report_scope(
                collection_acron_list=kwargs["collection_acron_list"],
                journal_acron_list=kwargs["journal_acron_list"],
                publication_year=kwargs["publication_year"],
                issue_folder=kwargs["issue_folder"],
                updated_from=kwargs["updated_from"],
                updated_to=kwargs["updated_to"],
            ),
            report_item_types(kwargs["report_type"], kwargs["content_type"]),
            user=self.request.user,
            task_name=triggered_by,
            status=ProblemReport.STATUS_QUEUED,
            # idioma em uso no admin (o Wagtail ativa a preferência do usuário)
            language=get_language(),
            max_items=kwargs["max_items"],
            report_type=kwargs["report_type"],
        )
        task_generate_problem_report.delay(
            user_id=self.request.user.id,
            triggered_by=triggered_by,
            problem_report_id=report.id,
            **kwargs,
        )
        messages.success(
            self.request,
            _(
                "Report requested from the current status (see the Status "
                "column). Reload this page until it shows “Ready” to download it."
            ),
        )
        return HttpResponseRedirect(self.list_url)
