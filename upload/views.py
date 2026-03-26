import logging
import os

from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from wagtail.snippets.views.snippets import CreateView, EditView, InspectView

from core.views import UserTrackingCreateView, UserTrackingEditView

from article.models import Article
from issue.models import Issue
from upload.models import Package, PkgValidationResult, choices
from upload.tasks import (
    task_receive_packages,
    task_publish_article,
    task_complete_journal_data,
    task_complete_issue_data,
)
from upload.utils import file_utils
from upload.utils import package_utils
from upload.utils.package_utils import coerce_package_and_errors, render_html
from upload.utils.xml_utils import XMLFormatError
from team.models import has_permission


# ===================================================================
# Create / Edit Views customizadas
# ===================================================================


class PackageZipCreateView(UserTrackingCreateView):
    """
    Upload de pacote ZIP.

    Sobrescreve post() porque precisa:
    1. Checar permissão antes do save
    2. Disparar task assíncrona após o save
    3. Redirecionar condicionalmente
    """

    def post(self, request, *args, **kwargs):
        if not has_permission(request.user):
            messages.error(request, _("Operation not available"))
            return redirect(self.get_add_url())

        self.form = self.get_form()
        if self.form.is_valid():
            pkg_zip = self.save_instance()
            pkg_zip.name, ext = os.path.splitext(os.path.basename(pkg_zip.file.name))
            pkg_zip.save()

            task_receive_packages.apply_async(
                kwargs=dict(
                    user_id=request.user.id,
                    pkg_zip_id=pkg_zip.id,
                )
            )

            if pkg_zip.show_package_validations:
                return redirect(f"/admin/upload/package?q={pkg_zip.name}")
            else:
                return redirect(self.get_success_url())
        else:
            return self.form_invalid(self.form)


class XMLInfoReportEditView(UserTrackingEditView):
    """
    Edição de XMLInfoReport.

    Sobrescreve post() para redirect customizado após save.
    """

    fields = ["package"]

    def post(self, request, *args, **kwargs):
        self.form = self.get_form()
        if self.form.is_valid():
            self.save_instance()
            messages.success(request, _("Success ..."))
            return redirect(self.get_success_url())
        else:
            return self.form_invalid(self.form)

    def get_success_url(self):
        report = self.instance
        return f"/admin/upload/package/inspect/{report.package.id}/?#xi"


class ValidationReportEditView(XMLInfoReportEditView):
    def get_success_url(self):
        report = self.instance
        return f"/admin/upload/package/inspect/{report.package.id}/?#vr{report.id}"


class XMLErrorReportEditView(XMLInfoReportEditView):
    def get_success_url(self):
        report = self.instance
        return f"/admin/upload/package/inspect/{report.package.id}/?#xer{report.id}"

    def post(self, request, *args, **kwargs):
        if not has_permission(request.user):
            messages.error(request, _("Operation not available"))
            return redirect(self.get_success_url())

        self.form = self.get_form()
        if self.form.is_valid():
            self.form.save_all(request.user)
            self.save_instance()
            return redirect(self.get_success_url())
        else:
            return self.form_invalid(self.form)


class UploadValidatorEditView(UserTrackingEditView):
    """
    Sobrescreve post() para checar permissão antes do save.
    """

    def post(self, request, *args, **kwargs):
        if not has_permission(request.user):
            messages.error(request, _("Operation not available"))
            return redirect(self.get_success_url())

        self.form = self.get_form()
        if self.form.is_valid():
            self.save_instance()
            return redirect(self.get_success_url())
        else:
            return self.form_invalid(self.form)


# ===================================================================
# Mixin e views de decisão de publicação
# ===================================================================


class PackageDecisionMixin:
    """
    Mixin para processar decisões de publicação de pacotes.

    Sobrescreve post() porque precisa:
    1. Checar permissão
    2. Salvar com tracking de updated_by
    3. Disparar tasks condicionais
    4. Processar decisão de QA
    5. Redirecionar com mensagem de sucesso/erro
    """

    success_message = _("The decision was executed as planned")
    error_message = _("There was an impediment to executing the decision.")
    permission_error_message = _("Operation not available")

    def get_task_function(self):
        """Pode ser sobrescrito se diferentes views usarem tasks diferentes."""
        return task_publish_article

    def process_decision(self, package, user, force_journal, force_issue):
        """Pode ser sobrescrito para customizar o processamento."""
        return package.process_qa_decision(
            user, self.get_task_function(), force_journal, force_issue
        )

    def post(self, request, *args, **kwargs):
        if not has_permission(request.user):
            messages.error(request, self.permission_error_message)
            return redirect(self.get_success_url())

        self.form = self.get_form()
        if not self.form.is_valid():
            return self.form_invalid(self.form)

        # save_instance() seta updated_by e salva
        package = self.save_instance()

        user = request.user
        force_journal_publication = self.form.cleaned_data.get("force_journal_publication")
        if force_journal_publication and package.journal:
            task_complete_journal_data.delay(
                user_id=user.id,
                username=user.username,
                journal_id=package.journal.id,
            )
        force_issue_publication = self.form.cleaned_data.get("force_issue_publication")
        if force_issue_publication and package.issue:
            task_complete_issue_data.delay(
                user_id=user.id,
                username=user.username,
                issue_id=package.issue.id,
            )

        if self.process_decision(
            package,
            user,
            force_journal_publication,
            force_issue_publication,
        ):
            messages.success(request, self.success_message)
            return redirect(self.get_success_url())
        else:
            messages.error(request, self.error_message)
            return self.form_invalid(self.form)


class QAPackageEditView(PackageDecisionMixin, UserTrackingEditView):
    pass


class ReadyToPublishPackageEditView(PackageDecisionMixin, UserTrackingEditView):
    success_message = _("Article successfully published")
    error_message = _("Failed to publish the article. Please try again.")


# ===================================================================
# Inspect View
# ===================================================================


class PackageAdminInspectView(InspectView):
    """
    MIGRAÇÃO: InspectView do wagtail.snippets tem a mesma interface
    que a do ModelAdmin para get_context_data().
    """

    def get_optimized_package_filepath_and_directory(self):
        _path = package_utils.generate_filepath_with_new_extension(
            self.instance.file.name,
            ".optz",
            True,
        )
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
        blocking_errors = list(
            PkgValidationResult.objects.filter(
                report__package=self.instance,
                status=choices.VALIDATION_RESULT_BLOCKING,
            ).values_list("message", flat=True)
        )
        data = {
            "pkg_zip_name": self.instance.pkg_zip.name,
            "linked": self.instance.linked.all(),
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
            "xml": self.instance.xml,
            "blocking_errors": blocking_errors,
        }

        return super().get_context_data(**data)


# ===================================================================
# Function-based views (sem mudança na migração)
# ===================================================================


def finish_deposit(request):
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(Package, pk=package_id)

        if package.finish_deposit(task_publish_article):
            messages.success(request, _("Package has been deposited"))
            return redirect("/admin/upload/package/")

        if not package.is_error_review_finished:
            messages.error(
                request,
                _("The XML package needs review and comment"),
            )
            return redirect(f"/admin/upload/package/inspect/{package_id}")

        if not package.is_acceptable_package:
            messages.error(
                request,
                _("Package deposit failed due to errors"),
            )
            messages.error(
                request,
                _("Correct package based on report and resubmit"),
            )
        return redirect(f"/admin/upload/package/inspect/{package_id}")


def download_errors(request):
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


def display_xml(request):
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(Package, pk=package_id)
        return render(
            request=request,
            template_name="modeladmin/upload/package/xml.html",
            context={"xml": package.xml},
        )

    return redirect(request.META.get("HTTP_REFERER"))


def preview_document(request):
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
    package_id = request.GET.get("package_id")
    user = request.user

    if not user.has_perm("upload.assign_package"):
        messages.error(request, _("You do not have permission to assign packages."))
    elif package_id:
        package = get_object_or_404(Package, pk=package_id)
        is_reassign = package.assignee is not None

    return redirect(f"/admin/upload/qapackage/edit/{package_id}")


def archive_package(request):
    package_id = request.GET.get("package_id")
    user = request.user

    if not user.has_perm("upload.user_can_packagezip_create"):
        messages.error(request, _("You do not have permission to archive packages."))
    elif package_id:
        package = get_object_or_404(Package, pk=package_id)

        if package.status == choices.PS_UNEXPECTED:
            package.status = choices.PS_ARCHIVED
            package.save()
            messages.success(request, _("Package was archived."))
        else:
            messages.warning(
                request,
                _("Unable to archive package which status = {}.").format(
                    package.status
                ),
            )
    return redirect(f"/admin/upload/package/")