from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext as _

from wagtail.core import hooks
from wagtail.contrib.modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from wagtail.contrib.modeladmin.views import CreateView, InspectView

from .button_helper import UploadButtonHelper
from .models import choices, Package, QAPackage, ValidationError
from .permission_helper import UploadPermissionHelper
from .tasks import run_validations
from .utils import package_utils


class UploadPackageCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)

        run_validations(self.object.file.name, self.object.id)
                
        return HttpResponseRedirect(self.get_success_url())


class PackageAdminInspectView(InspectView):
    def get_context_data(self):
        data = {
            'validation_errors': {},
            'package_id': self.instance.id,
            'status': self.instance.status,
            'languages': package_utils.get_languages(self.instance.file.name),
        }

        for ve in self.instance.validationerror_set.all():
            vek = ve.get_standardized_category_label()

            if vek not in data:
                data['validation_errors'][vek] = []

            data['validation_errors'][vek].append({
                'id': ve.id, 
                'inspect_url': ValidationErrorAdmin().url_helper.get_action_url('inspect', ve.id)
            })

        return super().get_context_data(**data)


class ValidationErrorAdminInspectView(InspectView):
    def get_context_data(self):
        try:
            data = self.instance.data.copy()
        except AttributeError:
            data = {}

        return super().get_context_data(**data)


class PackageAdmin(ModelAdmin):
    model = Package
    button_helper_class = UploadButtonHelper
    permission_helper_class = UploadPermissionHelper
    create_view_class = UploadPackageCreateView
    inspect_view_enabled=True
    inspect_view_class = PackageAdminInspectView
    menu_label = _('Packages')
    menu_icon = 'folder'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        'file',
        'status',
        'creator',
        'created',
        'updated',
        'updated_by',
    )
    list_filter = (
        'status',
    )
    search_fields = (
        'file',
        'creator',
        'updated_by',
    )
    inspect_view_fields = (
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


class QualityAnalystPackageAdmin(ModelAdmin):
    model = QAPackage
    permission_helper_class = UploadPermissionHelper
    menu_label = _('Waiting for QA')
    menu_icon = 'folder'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        'file',
        'creator',
        'created',
        'updated',
        'updated_by',
        'stat_disagree',
        'stat_unknown',
    )
    list_filter = ()
    search_fields = (
        'file',
        'creator',
        'updated_by',
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if self.permission_helper.user_can_access_all_packages(request.user, None):
            return qs.filter(status=choices.PS_QA)
    
        return qs.filter(creator=request.user)
    
class ValidationErrorAdmin(ModelAdmin):
    model = ValidationError
    inspect_view_enabled=True
    inspect_view_class=ValidationErrorAdminInspectView
    menu_label = _('Validation errors')
    menu_icon = 'error'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False
    list_display = (
        'category',
        'package',
        'message',
    )
    list_filter = (
        'category',
    )
    search_fields = (
        'message',
        'package',
    )
    inspect_view_fields = {
        'package',
        'category',
        'message',
    }


modeladmin_register(PackageAdmin)
modeladmin_register(ValidationErrorAdmin)


@hooks.register('register_admin_urls')
def register_disclosure_url():
    return [
        path('upload/package/',
        include('upload.urls', namespace='upload')),
    ]
