import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin
from wagtail.admin.widgets import Button

from core.users.permission_policies import TeamScopedEditView
from upload.admin_buttons import (
    get_document_downloads,
    get_document_sections,
    get_package_action_buttons,
)
from upload.forms import ReportResponsesForm
from upload.models import (
    BaseXMLValidationResult,
    XMLError,
    XMLErrorReport,
    XMLInfoReport,
    choices,
)
from upload.permission_policies import UploadModelPermissionPolicy
from upload.permissions import FINISH_DEPOSIT
from upload.querysets import get_scoped_package_queryset
from upload.tasks import task_upload_workflow_publish_article


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

        if self.status_filter in dict(choices.VALIDATION_RESULT_DISPLAY):
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
        return ReportResponsesForm(
            data=data,
            results=self.page.object_list,
            allow_completion=(
                not self.page.has_next()
                and not self.status_filter
                and not self.reaction_filter
                and not self.report.xml_producer_ack
            ),
        )

    def get_next_review_url(self, next_result_pk=None):
        query = self.request.GET.copy()
        query.pop("page", None)
        if self.page.has_next():
            # Reactions can leave the filtered set after saving. Anchor navigation
            # to the next result rather than skipping a now-shifted page.
            preceding = self.filtered_results.filter(pk__lt=next_result_pk).count()
            query["p"] = preceding // self.results_per_page + 1
        elif self.status_filter or self.reaction_filter:
            # A filtered last page is not the end of the full report.
            query.pop("status", None)
            query.pop("reaction", None)
            query.pop("p", None)
        else:
            reports = self.report.package.xml_error_report.filter(
                creation=choices.REPORT_CREATION_DONE
            ).order_by("created", "pk")
            for report in reports:
                if (report.created, report.pk) > (self.report.created, self.report.pk):
                    return reverse("upload:xml_error_report", args=[report.pk])
            return self.get_package_url()
        suffix = query.urlencode()

        return self.request.path + (f"?{suffix}" if suffix else "")

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
                        if isinstance(asset, dict)
                        and asset.get("component_type") == "asset"
                    ],
                    "message": result.message,
                    "advice": result.advice if isinstance(result, XMLError) else None,
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
            status_choices=choices.VALIDATION_RESULT_DISPLAY,
            reaction_filter=self.reaction_filter,
            reaction_choices=choices.ERROR_REACTION,
            can_respond=self.can_respond,
            form=form,
            report_in_progress=self.report.creation == choices.REPORT_CREATION_WIP,
            is_xml_errors=isinstance(self.report, XMLErrorReport),
            counts=summary["counts"],
            report_outcome=summary["state"],
            document_sections=get_document_sections(
                self.report.package_id, "validations"
            ),
            document_actions=get_package_action_buttons(
                self.request.user,
                self.report.package,
                Button,
                include_finish_deposit=True,
            ),
        )
        context.update(get_document_downloads(self.report.package))

        return context

    def post(self, request, *args, **kwargs):
        if not isinstance(self.report, XMLErrorReport):
            return HttpResponseNotAllowed(["GET"])
        if not self.can_respond:
            raise PermissionDenied
        action = request.POST.get("action", "save_responses")
        if action not in ("save_responses", "save_and_next"):
            return self.render_to_response(self.get_context_data(), status=400)

        form = self.get_form(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form), status=400)
        responses = {
            result.pk: form.cleaned_data[f"reaction_{result.pk}"]
            for result in self.page.object_list
        }
        # Compute before saving: changing reactions can move pagination boundaries.
        next_result_pk = None
        if action == "save_and_next" and self.page.has_next():
            next_result_pk = (
                self.page.paginator.page(self.page.next_page_number()).object_list[0].pk
            )
        complete_review = form.cleaned_data.get("complete_review", False)
        try:
            if complete_review:
                self.report.save_responses(
                    responses, request.user, complete_review=True
                )
            else:
                self.report.save_responses(responses, request.user)
        except ValidationError as error:
            if error.code != "report_changed":
                raise
            form.add_error(None, error)
            return self.render_to_response(self.get_context_data(form=form), status=409)

        next_url = (
            self.get_next_review_url(next_result_pk)
            if action == "save_and_next"
            else None
        )
        messages.success(
            request,
            (
                _("Review completed. The validation results have not been changed.")
                if complete_review
                else _("Responses saved. The validation results have not been changed.")
            ),
        )

        return redirect(next_url or request.get_full_path())


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
