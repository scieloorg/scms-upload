from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext as _

from wagtail.core import hooks
from wagtail.contrib.modeladmin.options import (ModelAdmin, modeladmin_register)
from wagtail.contrib.modeladmin.views import CreateView, InspectView

from .button_helper import UploadButtonHelper
from .groups import QUALITY_ANALYST
from .models import Package, ValidationError
from .permission_helper import UploadPermissionHelper
from .tasks import validate_xml_format


class UploadPackageCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)

        # FIXME: chamar método run_validations que dispara todas as validações, por ordem: 1) validate_xml_format --> 2) outras
        validate_xml_format(self.object.file.name, self.object.id)
                
        return HttpResponseRedirect(self.get_success_url())


class PackageAdminInspectView(InspectView):
    def get_context_data(self):
        data = {}

        for ve in self.instance.validationerror_set.all():
            vek = ve.get_standardized_category_label()

            if vek not in data:
                data[vek] = []

            data[vek].append(ValidationErrorAdmin().url_helper.get_action_url('inspect', ve.id))

        return super().get_context_data(**data)


class ValidationErrorAdminInspectView(InspectView):
    def get_context_data(self):
        data = {'start_row': self.instance.row}
        data.update({
            'snippet': [x.decode('utf-8') for x in eval(self.instance.snippet)]
            }
        )
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
        'file', 
        'created', 
        'updated',
        'files_list',
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        user_groups = [g.name for g in request.user.groups.all()]

        if request.user.is_superuser or request.user.is_staff or QUALITY_ANALYST in user_groups:
            return qs

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
