import logging

from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.views import CreateView, EditView, InspectView

from article.models import Article
from issue.models import Issue
from publication.tasks import task_publish_article
from upload.controller import receive_package
from upload.models import Package, choices
from upload.tasks import task_validate_original_zip_file
from upload.utils import file_utils
from upload.utils import package_utils
from upload.utils.package_utils import coerce_package_and_errors, render_html
from upload.utils.xml_utils import XMLFormatError


class PackageCreateView(CreateView):
    def form_valid(self, form):

        package = form.save_all(self.request.user)

        response = receive_package(self.request, package)

        # if response.get("error_type") == choices.VE_PACKAGE_FILE_ERROR:
        #     # error no arquivo
        #     messages.error(self.request, response.get("error"))
        #     return HttpResponseRedirect(self.request.META["HTTP_REFERER"])

        if response.get("error"):
            # error
            messages.error(self.request, response.get("error"))
            return redirect(f"/admin/upload/package/inspect/{package.id}")

        messages.success(
            self.request,
            _("Package has been successfully submitted and will be analyzed"),
        )

        # dispara a tarefa que realiza as validações de
        # assets, renditions, XML content etc

        task_validate_original_zip_file.apply_async(
            kwargs=dict(
                package_id=package.id,
                file_path=package.file.path,
                journal_id=response["journal"].id,
                issue_id=response["issue"].id,
                article_id=package.article and package.article.id or None,
            )
        )
        return HttpResponseRedirect(self.get_success_url())


class PackageAdminInspectView(InspectView):
    def get_optimized_package_filepath_and_directory(self):
        # Obtém caminho do pacote otimizado
        _path = package_utils.generate_filepath_with_new_extension(
            self.instance.file.name,
            ".optz",
            True,
        )

        # Obtém diretório em que o pacote otimizado foi extraído
        _directory = file_utils.get_file_url(
            dirname="", filename=file_utils.get_filename_from_filepath(_path)
        )

        return _path, _directory

    def set_pdf_paths(self, data, optz_dir):
        try:
            for rendition in package_utils.get_article_renditions_from_zipped_xml(
                self.instance.file.name
            ):
                package_files = file_utils.get_file_list_from_zip(
                    self.instance.file.name
                )
                document_name = package_utils.get_xml_filename(package_files)
                rendition_name = package_utils.get_rendition_expected_name(
                    rendition, document_name
                )
                data["pdfs"].append(
                    {
                        "base_uri": file_utils.os.path.join(optz_dir, rendition_name),
                        "language": rendition.language,
                    }
                )
        except XMLFormatError:
            data["pdfs"] = []

    def get_context_data(self):
        data = {
            "validation_results": {},
            "package_id": self.instance.id,
            "original_pkg": self.instance.file.name,
            "status": self.instance.status,
            "category": self.instance.category,
            "languages": package_utils.get_languages(self.instance.file.name),
            "pdfs": [],
            "reports": list(self.instance.reports),
            "xml_error_reports": list(self.instance.xml_error_reports),
            "xml_info_reports": list(self.instance.xml_info_reports),
            "summary": self.instance.summary,
        }

        # optz_file_path, optz_dir = self.get_optimized_package_filepath_and_directory()
        # data["optimized_pkg"] = optz_file_path
        # self.set_pdf_paths(data, optz_dir)

        return super().get_context_data(**data)


class XMLInfoReportEditView(EditView):

    fields = ["package"]

    def form_valid(self, form):

        report = form.save_all(self.request.user)

        messages.success(
            self.request,
            _("Success ..."),
        )

        # dispara a tarefa que realiza as validações de
        # assets, renditions, XML content etc
        return redirect(self.get_package_url())

    def get_package_url(self):
        report = self.instance
        return f"/admin/upload/package/inspect/{report.package.id}/?#xi"


class ValidationReportEditView(XMLInfoReportEditView):
    def get_package_url(self):
        report = self.instance
        return f"/admin/upload/package/inspect/{report.package.id}/?#vr{report.id}"


class XMLErrorReportEditView(XMLInfoReportEditView):
    def get_package_url(self):
        report = self.instance
        return f"/admin/upload/package/inspect/{report.package.id}/?#xer{report.id}"


class QAPackageEditView(EditView):
    def form_valid(self, form):
        package = form.save_all(self.request.user)

        process_qa_decision(package, self.request)

        return HttpResponseRedirect(self.get_success_url())


class ApprovedPackageEditView(EditView):
    def form_valid(self, form):
        package = form.save_all(self.request.user)

        process_qa_decision(package, self.request)

        return HttpResponseRedirect(self.get_success_url())


class UploadValidatorEditView(EditView):
    def form_valid(self, form):
        obj = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


def finish_deposit(request):
    """
    This view function enables the user to finish deposit of a package through the graphic-interface.
    """
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(Package, pk=package_id)

        if package.finish_deposit():
            # muda o status para a próxima etapa
            messages.success(request, _("Package has been deposited"))
            process_qa_decision(package, request)
            return redirect("/admin/upload/package/")

        if not package.is_error_review_finished:
            messages.error(
                request,
                _("XML producer must review the errors and comment them"),
            )
            return redirect(f"/admin/upload/package/inspect/{package_id}")

        if not package.is_acceptable_package:
            messages.error(
                request,
                _("Package could not be deposited due to validation errors"),
            )
            messages.error(
                request,
                _("Review the downloaded report and submit the corrected package"),
            )
        return redirect(f"/admin/upload/package/inspect/{package_id}")


def process_qa_decision(package, request):
    package.process_qa_decision(task_publish_article)


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
