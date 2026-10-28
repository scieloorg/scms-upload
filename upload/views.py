import logging
from functools import partial

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.http import content_disposition_header
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView
from django.views.generic.edit import FormView
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin
from wagtail.admin.widgets import Button
from wagtail.snippets.views.snippets import CreateView

from core.users.permission_policies import TeamScopedEditView
from upload.admin_buttons import (
    get_document_downloads,
    get_document_sections,
    get_package_action_buttons,
)
from upload.authorization import user_can_act_on_package
from upload.delegation import can_delegate_review, delegate_review
from upload.forms import DelegateReviewForm, ReportResponsesForm
from upload.models import (
    BaseXMLValidationResult,
    Package,
    UploadProcResult,
    XMLError,
    XMLErrorReport,
    XMLInfoReport,
    choices,
)
from upload.permission_policies import UploadModelPermissionPolicy
from upload.permissions import (
    ASSIGN_PACKAGE,
    FINISH_DEPOSIT,
    PUBLISH_PACKAGE,
    REPUBLISH_PACKAGE,
    REQUEST_CORRECTION,
)
from upload.publication_status import (
    PUBLICATION_ATTEMPT_PREFIX,
    PUBLICATION_FAILED,
    PUBLICATION_QUEUED,
    publication_situation,
)
from upload.querysets import get_scoped_package_queryset
from upload.tasks import (
    task_receive_packages,
    task_republish_articles,
    task_upload_workflow_publish_article,
)
from upload.utils.package_utils import render_html


class ValidationReportView(WagtailAdminTemplateMixin, TemplateView):
    page_title = _("Document")
    header_icon = "doc-full"
    template_name = "upload/reports/detail.html"
    http_method_names = ["get", "post", "head", "options"]
    model = None
    report_kind = None
    results_per_page = 20
    pagination_neighbors = 1
    pagination_end_pages = 1

    def dispatch(self, request, *args, **kwargs):
        self.policy = UploadModelPermissionPolicy(self.model)

        if not self.policy.user_has_any_permission(request.user, ("view", "change")):
            raise PermissionDenied

        self.report = get_object_or_404(
            self.model.objects.select_related("package"),
            pk=kwargs["pk"],
            package__in=get_scoped_package_queryset(request.user),
        )
        self.page_subtitle = str(self.report.package)
        self.can_respond = (
            isinstance(self.report, XMLErrorReport)
            and self.policy.user_has_permission(request.user, "change")
            and self.report.creation == choices.REPORT_CREATION_DONE
        )

        self.results = self.report.validation_results.order_by("pk")
        self.filtered_results = self.results

        self.status_filter = (
            ""
            if isinstance(self.report, XMLInfoReport)
            else request.GET.get("status", "")
        )

        if self.status_filter in dict(choices.VALIDATION_RESULT):
            self.filtered_results = self.filtered_results.filter(
                status=self.status_filter
            )

        self.reaction_filter = request.GET.get("reaction", "")
        if isinstance(self.report, XMLErrorReport) and self.reaction_filter in dict(
            choices.ERROR_REACTION
        ):
            self.filtered_results = self.filtered_results.filter(
                reaction=self.reaction_filter
            )

        self.page = Paginator(self.filtered_results, self.results_per_page).get_page(
            request.GET.get("p", request.GET.get("page"))
        )

        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return [
            *super().get_breadcrumbs_items(),
            {
                "url": reverse("wagtailsnippets_upload_package:list"),
                "label": _("Documents"),
            },
            {"url": "", "label": self.page_title, "sublabel": self.get_page_subtitle()},
        ]

    def get_package_url(self):
        anchor = {"xml-errors": "xer", "package-checks": "vr", "xml-information": "xi"}
        suffix = "" if self.report_kind == "xml-information" else self.report.pk

        return (
            reverse(
                "wagtailsnippets_upload_package:inspect", args=[self.report.package_id]
            )
            + f"?tab=validations#{anchor[self.report_kind]}{suffix}"
        )

    def get_form(self, data=None):
        return ReportResponsesForm(data=data, results=self.page.object_list)

    def get_results_context(self, form=None):
        results = []
        for result in self.page.object_list:
            data = result.data if isinstance(result.data, dict) else {}
            details = data.get("data")
            details = details if isinstance(details, dict) else {}
            location = [details.get("contrib_full_name"), data.get("parent_lang")]
            if isinstance(result, BaseXMLValidationResult):
                location.extend((result.parent_id, result.attribute))

            assets = result.data if isinstance(result.data, list) else []
            results.append(
                {
                    "result": result,
                    "response_field": form[f"reaction_{result.pk}"] if form else None,
                    "reference": details.get("ref_id"),
                    "location": " · ".join(str(value) for value in location if value),
                    "line": data.get("apparent_line"),
                    "asset": data if data.get("component_type") == "asset" else {},
                    "assets": [
                        asset
                        for asset in assets
                        if isinstance(asset, dict) and asset.get("component_type") == "asset"
                    ],
                    "message": data.get("message") or result.message,
                    "advice": data.get("advice") or (result.advice if isinstance(result, XMLError) else None),
                }
            )

        return results

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        summary = self.report.validation_summary
        form = kwargs.get("form")
        if form is None and self.can_respond:
            form = self.get_form()

        context.update(
            report=self.report,
            is_xml_info=isinstance(self.report, XMLInfoReport),
            success_total=summary["success_total"],
            document_identity=self.report.package.document_identity,
            report_title=self.report.display_heading,
            package_url=self.get_package_url(),
            results=self.get_results_context(form),
            page_obj=self.page,
            pagination_pages=list(
                self.page.paginator.get_elided_page_range(
                    self.page.number,
                    on_each_side=self.pagination_neighbors,
                    on_ends=self.pagination_end_pages,
                )
            ),
            status_filter=self.status_filter,
            status_choices=choices.VALIDATION_RESULT,
            reaction_filter=self.reaction_filter,
            reaction_choices=choices.ERROR_REACTION,
            can_respond=self.can_respond,
            form=form,
            report_in_progress=self.report.creation == choices.REPORT_CREATION_WIP,
            is_xml_errors=isinstance(self.report, XMLErrorReport),
            counts=summary["counts"],
            report_outcome=summary["state"],
            document_sections=get_document_sections(self.report.package_id, "validations"),
            document_actions=get_package_action_buttons(
                self.request.user, self.report.package, Button, include_finish_deposit=True
            ),
        )
        context.update(get_document_downloads(self.report.package))
        return context

    def post(self, request, *args, **kwargs):
        if not isinstance(self.report, XMLErrorReport):
            return HttpResponseNotAllowed(["GET"])
        if not self.can_respond:
            raise PermissionDenied
        if request.POST.get("action", "save_responses") != "save_responses":
            return self.render_to_response(self.get_context_data(), status=400)

        form = self.get_form(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form), status=400)
        responses = {
            result.pk: form.cleaned_data[f"reaction_{result.pk}"]
            for result in self.page.object_list
        }
        try:
            self.report.save_responses(responses, request.user)
        except ValidationError as error:
            if error.code != "report_changed":
                raise
            form.add_error(None, error)
            return self.render_to_response(self.get_context_data(form=form), status=409)

        messages.success(
            request, _("Responses saved. The validation results have not been changed.")
        )
        return redirect(request.get_full_path())


class DelegateReviewView(WagtailAdminTemplateMixin, FormView):
    page_title = _("Delegate review")
    header_icon = ""
    template_name = "upload/decisions/delegate.html"
    form_class = DelegateReviewForm

    def dispatch(self, request, *args, **kwargs):
        self.package = get_object_or_404(
            get_scoped_package_queryset(request.user, ASSIGN_PACKAGE),
            pk=kwargs["pk"],
        )

        if not can_delegate_review(request.user, self.package):
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "package": self.package}

    def get_success_url(self):
        return reverse("wagtailsnippets_upload_package:inspect", args=[self.package.pk])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context.update(
            document_identity=self.package.document_identity,
            document_url=self.get_success_url(),
            submit_button_label=_("Save assignment"),
            submit_button_active_label=_("Saving…"),
        )

        return context

    def form_valid(self, form):
        try:
            delegate_review(
                self.request.user,
                self.package.pk,
                form.cleaned_data["reviewer"].pk,
                form.cleaned_data["instructions"],
            )
        except ValidationError as error:
            form.add_error("reviewer", error)
            return self.form_invalid(form)

        messages.success(self.request, _("Review assignment saved."))
        return redirect(self.get_success_url())


class PackageZipCreateView(CreateView):
    def form_valid(self, form):
        if not self.permission_policy.user_has_permission(
            self.request.user,
            "add",
        ):
            messages.error(
                self.request,
                _("Operation not available"),
            )
            return HttpResponseRedirect(self.get_success_url())

        pkg_zip = form.save_all(self.request.user)
        transaction.on_commit(
            partial(
                task_receive_packages.apply_async,
                kwargs=dict(
                    user_id=self.request.user.id,
                    pkg_zip_id=pkg_zip.id,
                ),
            )
        )
        documents_url = reverse("wagtailsnippets_upload_package:list")
        messages.success(
            self.request,
            format_html(
                '{} <a href="{}?pkg_zip_id={}">{}</a>',
                _(
                    "Package received. Processing runs in the background. "
                    "Follow its progress in Document tracking."
                ),
                documents_url,
                pkg_zip.pk,
                _("View documents"),
            ),
        )

        return HttpResponseRedirect(self.get_success_url())


class XMLInfoReportEditView(TeamScopedEditView):
    def get_success_url(self):
        return self.get_package_url()

    def get_breadcrumbs_items(self):
        items = super().get_breadcrumbs_items()
        items.insert(-1, {"url": self.get_package_url(), "label": _("Document")})

        return items

    def form_valid(self, form):
        form.save_all(self.request.user)

        messages.success(
            self.request,
            _("Success ..."),
        )

        return redirect(self.get_package_url())

    def get_package_url(self):
        report = self.object
        return (
            reverse("wagtailsnippets_upload_package:inspect", args=[report.package_id])
            + "?tab=validations#xi"
        )


class ValidationReportEditView(XMLInfoReportEditView):
    def get_package_url(self):
        report = self.object
        return (
            reverse("wagtailsnippets_upload_package:inspect", args=[report.package_id])
            + f"?tab=validations#vr{report.id}"
        )


class XMLErrorReportEditView(XMLInfoReportEditView):
    def get_package_url(self):
        report = self.object
        return (
            reverse("wagtailsnippets_upload_package:inspect", args=[report.package_id])
            + f"?tab=validations#xer{report.id}"
        )


class PackageDecisionMixin:
    success_message = _("Decision recorded successfully")
    error_message = _("Unable to complete the operation. Check the form and try again.")
    permission_error_message = _("Operation not available")

    page_subtitle = _("Record decision")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            document_identity=self.object.document_identity,
            document_url=self.get_success_url(),
        )

        return context

    def get_success_url(self):
        return reverse("wagtailsnippets_upload_package:inspect", args=[self.object.pk])

    def get_task_function(self):
        return task_upload_workflow_publish_article

    def process_decision(self, package, user, force_journal, force_issue):
        return package.process_qa_decision(
            user, self.get_task_function(), force_journal, force_issue
        )

    def form_valid(self, form):
        decision = form.cleaned_data.get("qa_decision")
        if decision == choices.PS_PENDING_CORRECTION:
            permission = REQUEST_CORRECTION
        elif decision == choices.PS_PENDING_QA_DECISION:
            raise PermissionDenied
        else:
            permission = PUBLISH_PACKAGE
        if not user_can_act_on_package(self.request.user, permission, form.instance):
            messages.error(self.request, self.permission_error_message)
            return HttpResponseRedirect(self.get_success_url())

        package = form.save_all(self.request.user)

        force_journal_publication = form.cleaned_data.get("force_journal_publication")
        if permission == PUBLISH_PACKAGE and not package.journal:
            messages.error(
                self.request,
                _(
                    "Package journal was not identified in the system or is not registered"
                ),
            )
            return HttpResponseRedirect(self.get_success_url())

        force_issue_publication = form.cleaned_data.get("force_issue_publication")
        if permission == PUBLISH_PACKAGE and not package.issue:
            messages.error(
                self.request,
                _(
                    "Package issue was not identified in the system or is not registered"
                ),
            )
            return HttpResponseRedirect(self.get_success_url())

        if self.process_decision(
            package,
            self.request.user,
            force_journal_publication,
            force_issue_publication,
        ):
            messages.success(self.request, self.success_message)
            return HttpResponseRedirect(self.get_success_url())
        messages.error(self.request, self.error_message)
        return self.form_invalid(form)


class QAPackageEditView(PackageDecisionMixin, TeamScopedEditView):
    pass


class ReadyToPublishPackageEditView(PackageDecisionMixin, TeamScopedEditView):
    pass


@transaction.atomic
def retry_publication(request):
    if not request.user.has_perm(f"upload.{PUBLISH_PACKAGE}"):
        messages.error(request, _("Operation not available"))
        return redirect("wagtailsnippets_upload_package:list")

    package_id = request.POST.get("package_id") or request.GET.get("package_id")
    package = get_object_or_404(
        Package.objects.filter(
            pk__in=get_scoped_package_queryset(request.user, PUBLISH_PACKAGE).values(
                "pk"
            ),
        ).select_for_update(),
        pk=package_id,
    )
    destination = reverse("wagtailsnippets_upload_package:inspect", args=[package.pk])
    purpose = "PUBLIC" if package.status == choices.PS_READY_TO_PUBLISH else "QA"
    if (
        package.status not in (choices.PS_READY_TO_PREVIEW, choices.PS_READY_TO_PUBLISH)
        or publication_situation(package, purpose)["state"] != PUBLICATION_FAILED
    ):
        messages.error(
            request, _("No failed publication attempt is available to retry.")
        )
        return redirect(destination)

    if request.method != "POST":
        return render(
            request,
            "upload/admin/package/confirm_action.html",
            {
                "title": _("Retry publication"),
                "message": _(
                    "Retry the failed publication using the existing authorization. "
                    "The document and its validation results will be preserved."
                ),
                "submit_label": _("Retry publication"),
                "package": package,
                "cancel_url": destination,
            },
        )

    attempt = UploadProcResult.create(
        request.user,
        package,
        f"{PUBLICATION_ATTEMPT_PREFIX} {[purpose]}",
    )
    attempt.detail = {"state": PUBLICATION_QUEUED, "websites": [purpose]}
    attempt.save(update_fields=["detail"])
    transaction.on_commit(
        partial(
            task_upload_workflow_publish_article.apply_async,
            kwargs={
                "user_id": request.user.pk,
                "username": request.user.username,
                "upload_package_id": package.pk,
                "websites": [purpose],
            },
        )
    )
    messages.success(request, _("Publication retry scheduled."))
    return redirect(destination)


def finish_deposit(request):
    if not request.user.has_perm(f"upload.{FINISH_DEPOSIT}"):
        messages.error(request, _("Operation not available"))
        return redirect("wagtailsnippets_upload_package:list")

    package_id = request.POST.get("package_id") or request.GET.get("package_id")
    if not package_id:
        messages.error(request, _("Package not informed"))
        return redirect("wagtailsnippets_upload_package:list")

    package = get_object_or_404(
        get_scoped_package_queryset(request.user, FINISH_DEPOSIT),
        pk=package_id,
    )

    if request.method != "POST":
        return render(
            request,
            "upload/admin/package/confirm_action.html",
            {
                "title": _("Submit validation responses"),
                "message": _(
                    "The ZIP has already been received. Submit the validation responses "
                    "to determine whether the document needs corrections or can proceed "
                    "with processing."
                ),
                "submit_label": _("Submit validation responses"),
                "package": package,
                "cancel_url": reverse(
                    "wagtailsnippets_upload_package:inspect", args=[package_id]
                ),
            },
        )

    if package.finish_deposit(task_upload_workflow_publish_article):
        messages.success(
            request, _("Validation responses processed. Check the document status.")
        )
        return redirect("wagtailsnippets_upload_package:list")

    if not package.is_error_review_finished:
        messages.error(
            request,
            _("The XML package needs review and comment"),
        )
        return redirect("wagtailsnippets_upload_package:inspect", pk=package_id)

    if not package.is_acceptable_package:
        messages.error(
            request,
            _("Package deposit failed due to errors"),
        )
        messages.error(
            request,
            _("Correct package based on report and resubmit"),
        )

    return redirect("wagtailsnippets_upload_package:inspect", pk=package_id)


def download_errors(request):
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(
            get_scoped_package_queryset(request.user), pk=package_id
        )

    try:
        errors = package.get_errors_report_content()
        response = HttpResponse(errors["content"], content_type="text/csv")
        response["Content-Disposition"] = "inline; filename=" + errors["filename"]
        logging.info(errors)
        return response
    except Exception as e:
        logging.exception(e)
        raise Http404


def display_xml(request):
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(
            get_scoped_package_queryset(request.user), pk=package_id
        )
        if request.GET.get("download") == "1":
            response = HttpResponse(
                package.xml, content_type="application/xml; charset=utf-8"
            )
            response["Content-Disposition"] = content_disposition_header(
                True,
                f"{package.package_name}.xml",
            )
            return response
        return render(
            request=request,
            template_name="modeladmin/upload/package/xml.html",
            context={"xml": package.xml},
        )

    return redirect(request.META.get("HTTP_REFERER"))


def preview_document(request):
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(
            get_scoped_package_queryset(request.user), pk=package_id
        )
        language = request.GET.get("language")
        xml_path = request.GET.get("xml_path")

        document_html = render_html(package.file.name, xml_path, language)

        return render(
            request=request,
            template_name="modeladmin/upload/package/preview_document.html",
            context={"document": document_html, "package_status": package.status},
        )

    return redirect(request.META.get("HTTP_REFERER"))


def assign(request):
    package_id = request.GET.get("package_id")
    user = request.user

    if not user.has_perm(f"upload.{ASSIGN_PACKAGE}"):
        messages.error(request, _("You do not have permission to assign packages."))
        return redirect("wagtailsnippets_upload_package:list")

    if not package_id:
        messages.error(request, _("Package not informed"))
        return redirect("wagtailsnippets_upload_package:list")

    get_object_or_404(
        get_scoped_package_queryset(request.user, ASSIGN_PACKAGE), pk=package_id
    )

    return redirect("upload:delegate_review", pk=package_id)


def archive_package(request):
    user = request.user

    if not user.has_perm("upload.change_package"):
        messages.error(request, _("You do not have permission to archive packages."))
        return redirect("wagtailsnippets_upload_package:list")

    package_id = request.POST.get("package_id") or request.GET.get("package_id")
    if not package_id:
        messages.error(request, _("Package not informed"))
        return redirect("wagtailsnippets_upload_package:list")

    package = get_object_or_404(
        get_scoped_package_queryset(request.user),
        pk=package_id,
    )

    if request.method != "POST":
        return render(
            request,
            "upload/admin/package/confirm_action.html",
            {
                "title": _("Archive package"),
                "message": _("Confirm archiving package '{}'?").format(package),
                "submit_label": _("Archive"),
                "package": package,
                "cancel_url": reverse("wagtailsnippets_upload_package:list"),
            },
        )

    if package.status == choices.PS_UNEXPECTED:
        package.status = choices.PS_ARCHIVED
        package.save()
        messages.success(request, _("Package was archived."))
    else:
        messages.warning(
            request,
            _("Unable to archive package which status = {}.").format(package.status),
        )

    return redirect("wagtailsnippets_upload_package:list")


def republish_selected(request):
    """
    Agenda republicação de um conjunto específico de pacotes selecionados na listagem.
    Os IDs dos pacotes chegam via GET (parâmetro package_ids, separados por vírgula)
    na primeira exibição do formulário, e via POST (campo oculto) na confirmação.
    """
    if not request.user.has_perm(f"upload.{REPUBLISH_PACKAGE}"):
        messages.error(request, _("Operation not available"))
        return redirect("wagtailsnippets_upload_package:list")

    if request.method == "POST":
        website_kind = request.POST.get("website_kind") or None
        package_ids_raw = request.POST.get("package_ids", "")
        package_ids = [
            int(pk) for pk in package_ids_raw.split(",") if pk.strip().isdigit()
        ]

        if not package_ids:
            messages.error(request, _("No packages selected."))
            return redirect("wagtailsnippets_upload_package:list")

        scoped_ids = set(
            get_scoped_package_queryset(request.user, REPUBLISH_PACKAGE)
            .filter(pk__in=package_ids)
            .values_list("pk", flat=True)
        )
        if scoped_ids != set(package_ids):
            messages.error(request, _("One or more packages are outside your scope."))
            return redirect("wagtailsnippets_upload_package:list")

        task_republish_articles.delay(
            username=request.user.username,
            user_id=request.user.id,
            website_kind=website_kind,
            package_ids=package_ids,
        )
        messages.success(
            request,
            _(
                "Batch republication of %(count)d package(s) scheduled for %(website)s website."
            )
            % {
                "count": len(package_ids),
                "website": choices.WEBSITE_ENVIRONMENT_LABELS.get(website_kind, _("all")),
            },
        )
        return redirect("wagtailsnippets_upload_package:list")

    package_ids_raw = request.GET.get("package_ids", "")
    package_ids = [pk for pk in package_ids_raw.split(",") if pk.strip().isdigit()]

    if not package_ids:
        messages.error(request, _("No packages selected."))
        return redirect("wagtailsnippets_upload_package:list")

    scoped_ids = set(
        get_scoped_package_queryset(request.user, REPUBLISH_PACKAGE)
        .filter(pk__in=package_ids)
        .values_list("pk", flat=True)
    )
    if scoped_ids != {int(pk) for pk in package_ids}:
        messages.error(request, _("One or more packages are outside your scope."))
        return redirect("wagtailsnippets_upload_package:list")

    return render(
        request,
        "upload/admin/package/republish_selected.html",
        {
            "website_kinds": choices.WEBSITE_ENVIRONMENTS,
            "package_ids": ",".join(package_ids),
            "package_count": len(package_ids),
        },
    )


def redirect_upload_url(request, model_name, subpath):
    url = reverse(f"wagtailsnippets_upload_{model_name}:list") + subpath
    query = request.META.get("QUERY_STRING")
    if query:
        url += "?" + query

    return redirect(url, preserve_request=request.method not in ("GET", "HEAD"))
