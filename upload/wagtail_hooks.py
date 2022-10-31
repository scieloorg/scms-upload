from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext as _
from upload.utils import file_utils
from upload.utils.xml_utils import XMLFormatError

from wagtail.core import hooks
from wagtail.contrib.modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from wagtail.contrib.modeladmin.views import CreateView, InspectView

from article.models import Article
from config.menu import get_menu_order
from issue.models import Issue

from .button_helper import UploadButtonHelper
from .models import QAPackage, choices, Package, ValidationResult
from .permission_helper import UploadPermissionHelper
from .tasks import run_validations
from .utils import package_utils

import json


class PackageCreateView(CreateView):
    def get_instance(self):
        package_obj = super().get_instance()

        pkg_category = self.request.GET.get('package_category')
        if pkg_category:
            package_obj.category = pkg_category

        article_id = self.request.GET.get('article_id')
        if article_id:
            try:
                package_obj.article = Article.objects.get(pk=article_id)
            except Article.DoesNotExist:
                ...

        return package_obj

    def form_valid(self, form):
        article_data = self.request.POST.get('article')
        article_json = json.loads(article_data) or {}
        article_id = article_json.get('pk')
        try:
            article = Article.objects.get(pk=article_id)
        except (Article.DoesNotExist, ValueError):
            article = None

        issue_data = self.request.POST.get('issue')
        issue_json = json.loads(issue_data) or {}
        issue_id = issue_json.get('pk')
        try:
            issue = Issue.objects.get(pk=issue_id)
        except (Issue.DoesNotExist, ValueError):
            issue = None

        self.object = form.save_all(self.request.user, article, issue)

        if self.object.category in (
            choices.PC_CORRECTION, 
            choices.PC_ERRATUM
        ):
            if self.object.article is None:
                messages.error(
                    self.request,
                    _('It is necessary to select an Article.'),
                )
                return HttpResponseRedirect(self.request.META['HTTP_REFERER'])
            else:
                messages.success(
                self.request,
                _('Package to change article has been successfully submitted.')
            )

        if self.object.category == choices.PC_NEW_DOCUMENT:
            if self.object.issue is None:
                messages.error(
                    self.request,
                    _('It is necessary to select an Issue.')
                )
                return HttpResponseRedirect(self.request.META['HTTP_REFERER'])
            else:
                messages.success(
                self.request,
                _('Package to create article has been successfully submitted.')
            )

        run_validations(
            self.object.file.name, 
            self.object.id, 
            self.object.category, 
            article_id, 
            issue_id,
        )
                
        return HttpResponseRedirect(self.get_success_url())


class PackageAdminInspectView(InspectView):
    def get_optimized_package_filepath_and_directory(self):
        # Obtém caminho do pacote otimizado
        _path = package_utils.generate_filepath_with_new_extension(
            self.instance.file.name, 
            '.optz',
            True,
        )

        # Obtém diretório em que o pacote otimizado foi extraído
        _directory = file_utils.get_file_url(
            dirname='',
            filename=file_utils.get_filename_from_filepath(_path)
        )

        return _path, _directory

    def set_pdf_paths(self, data, optz_dir):
        try:
            for rendition in package_utils.get_article_renditions_from_zipped_xml(self.instance.file.name):
                package_files = file_utils.get_file_list_from_zip(self.instance.file.name)
                document_name = package_utils.get_xml_filename(package_files)
                rendition_name = package_utils.get_rendition_expected_name(rendition, document_name)
                data['pdfs'].append({
                    'base_uri': file_utils.os.path.join(optz_dir, rendition_name),
                    'language': rendition.language,
                })
        except XMLFormatError:
            data['pdfs'] = []

    def get_context_data(self):
        data = {
            'validation_results': {},
            'package_id': self.instance.id,
            'original_pkg': self.instance.file.name,
            'status': self.instance.status,
            'category': self.instance.category,
            'languages': package_utils.get_languages(self.instance.file.name),
            'pdfs': []
        }

        optz_file_path, optz_dir = self.get_optimized_package_filepath_and_directory()
        data['optimized_pkg'] = optz_file_path
        self.set_pdf_paths(data, optz_dir)

        for vr in self.instance.validationresult_set.all():
            vr_name = vr.report_name()
            if vr_name not in data['validation_results']:
                data['validation_results'][vr_name] = {'status': vr.status}

            if vr.status == choices.VS_DISAPPROVED:
                if data['validation_results'][vr_name] != choices.VS_DISAPPROVED:
                    data['validation_results'][vr_name].update({'status': vr.status})

                if hasattr(vr, 'analysis'):
                    data['validation_results']['qa'] = self.instance.status

            if vr_name == choices.VR_XML_OR_DTD:
                if 'xmls' not in data['validation_results'][vr_name]:
                    data['validation_results'][vr_name]['xmls'] = []

                if vr.data and isinstance(vr.data, dict):
                    data['validation_results'][vr_name]['xmls'].append({
                        'xml_name': vr.data.get('xml_path'),
                        'base_uri': file_utils.os.path.join(optz_dir, vr.data.get('xml_path')),
                        'inspect_uri': ValidationResultAdmin().url_helper.get_action_url('inspect', vr.id)
                    })

        return super().get_context_data(**data)


class ValidationResultCreateView(CreateView):
class ValidationResultAdminInspectView(InspectView):
    def get_context_data(self):
        try:
            data = self.instance.data.copy()
        except AttributeError:
            data = {}
        data['package_url'] = f'/admin/upload/package/inspect/{self.instance.package.id}'
        return super().get_context_data(**data)


class PackageAdmin(ModelAdmin):
    model = Package
    button_helper_class = UploadButtonHelper
    permission_helper_class = UploadPermissionHelper
    create_view_class = PackageCreateView
    inspect_view_enabled=True
    inspect_view_class = PackageAdminInspectView
    menu_label = _('Packages')
    menu_icon = 'folder'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        'article',
        'issue',
        'category',
        'file',
        'status',
        'assignee',
        'creator',
        'created',
        'updated',
        'updated_by',
    )
    list_filter = (
        'category',
        'status',
    )
    search_fields = (
        'file',
        'issue__officialjournal__title',
        'article__pid_v3',
        'creator__username',
        'updated_by__username',
    )
    inspect_view_fields = (
        'article',
        'issue',
        'category',
        'status',
        'file', 
        'created', 
        'updated',
        'files_list',
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if self.permission_helper.user_can_access_all_packages(request.user, None):
            return qs
    
        return qs.filter(creator=request.user)


class ValidationResultAdmin(ModelAdmin):
    model = ValidationResult
    permission_helper_class = UploadPermissionHelper
    create_view_class = ValidationResultCreateView
    inspect_view_enabled=True
    inspect_view_class=ValidationResultAdminInspectView
    menu_label = _('Validation results')
    menu_icon = 'error'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False
    list_display = (
        'report_name',
        'category',
        'status',
        'package',
        'message',
    )
    list_filter = (
        'category',
        'status',
    )
    search_fields = (
        'message',
        'package__file',
    )
    inspect_view_fields = {
        'package',
        'category',
        'message',
        'data',
        'status',
    }

    def get_queryset(self, request):
        if request.user.is_superuser or self.permission_helper.user_can_access_all_packages(request.user, None):
            return super().get_queryset(request)

        return super().get_queryset(request).filter(package__creator=request.user)


class QualityAnalysisPackageAdmin(ModelAdmin):
    model = QAPackage
    button_helper_class = UploadButtonHelper
    permission_helper_class = UploadPermissionHelper
    menu_label = _('Waiting for QA')
    menu_icon = 'folder'
    menu_order = 200
    inspect_view_enabled=True
    inspect_view_class = PackageAdminInspectView
    inspect_template_name = 'modeladmin/upload/package/inspect.html'
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        'file',
        'assignee',
        'creator',
        'created',
        'updated',
        'updated_by',
    )
    list_filter = (
        'assignee',
    )
    search_fields = (
        'file',
        'assignee__username',
        'creator__username',
        'updated_by__username',
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if self.permission_helper.user_can_access_all_packages(request.user, None):
            return qs.filter(status=choices.PS_QA)
    
        return qs.none()


class UploadModelAdminGroup(ModelAdminGroup):
    menu_icon = 'folder'
    menu_label = 'Upload'
    items = (PackageAdmin, ValidationResultAdmin, QualityAnalysisPackageAdmin)
    menu_order = get_menu_order('upload')


modeladmin_register(UploadModelAdminGroup)


@hooks.register('register_admin_urls')
def register_disclosure_url():
    return [
        path('upload/',
        include('upload.urls', namespace='upload')),
    ]
