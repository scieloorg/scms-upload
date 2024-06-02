import logging

from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.views import CreateView, EditView, InspectView

from .models import Package, choices
from .utils.package_utils import coerce_package_and_errors, render_html


class XMLErrorReportEditView(EditView):
    def form_valid(self, form):

        report = form.save_all(self.request.user)

        messages.success(
            self.request,
            _("Success ..."),
        )

        # dispara a tarefa que realiza as validações de
        # assets, renditions, XML content etc
        return redirect(
            f"/admin/upload/package/inspect/{report.package.id}/?#xer{report.id}"
        )


class QAPackageEditView(EditView):
    def form_valid(self, form):
        saved = form.save_all(self.request.user)
        messages.success(
            self.request,
            _("Success ..."),
        )
        return HttpResponseRedirect(self.get_success_url())


def finish_deposit(request):
    """
    This view function enables the user to finish deposit of a package through the graphic-interface.
    """
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(Package, pk=package_id)

        if package.finish_deposit():
            messages.success(request, _("Package has been submitted to QA"))
        else:
            messages.warning(
                request,
                _(
                    "Package could not be submitted to QA due to validation errors."
                ),
            )
            messages.warning(
                request,
                _(
                    "Fix the downloaded errors and submit the corrected package"
                ),
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
    return redirect(f"/admin/upload/package/inspect/{package_id}")


def download_errors(request):
    """
    This view function enables the user to finish deposit of a package through the graphic-interface.
    """
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(Package, pk=package_id)

    try:
        errors = package.get_errors_report_content()
        response = HttpResponse(errors["content"], content_type="text/csv")
        response["Content-Disposition"] = "inline; filename=" + errors["filename"]
        logging.info(errors)
        return response
    except Exception as e:
        logging.exception(e)
        raise Http404


def preview_document(request):
    """
    This view function enables the user to see a preview of HTML
    """
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(Package, pk=package_id)
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
    """
    Assign review to a team member or decide about the package
    """
    package_id = request.GET.get("package_id")
    user = request.user

    if not user.has_perm("upload.assign_package"):
        messages.error(request, _("You do not have permission to assign packages."))
    elif package_id:
        package = get_object_or_404(Package, pk=package_id)
        is_reassign = package.assignee is not None

        # package.assignee = user
        # package.save()

        # if not is_reassign:
        #     messages.success(request, _("Package has been assigned with success."))
        # else:
        #     messages.warning(request, _("Package has been reassigned with success."))

    return redirect(f"/admin/upload/qapackage/edit/{package_id}")
