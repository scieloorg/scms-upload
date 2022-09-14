from django.db.models import Q
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
        'article',
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
        'article__pid_v3',
        'creator__username',
        'updated_by__username',
    )
    inspect_view_fields = (
        'article',
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
    
        return qs.filter(
            Q(creator=request.user) |
            Q(article__requestarticlechange__demanded_user=request.user)
        )


class QualityAnalystPackageAdmin(ModelAdmin):
    model = QAPackage
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
        'creator',
        'created',
        'updated',
        'updated_by',
        'stat_disagree',
        'stat_incapable_to_fix',
    )
    list_filter = ()
    search_fields = (
        'file',
        'creator__username',
        'updated_by__username',
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if self.permission_helper.user_can_access_all_packages(request.user, None):
            return qs.filter(status__in=[choices.PS_QA, choices.PS_ACCEPTED])
    
        return qs.filter(creator=request.user)
    
    def _get_all_validation_errors(self, obj):
        return [ve.resolution for ve in obj.validationerror_set.all()]

    def _get_stats(self, obj, value):
        all_objs = self._get_all_validation_errors(obj)
        value_objs = [o for o in all_objs if o.action == value]
        return len(value_objs), len(all_objs)

    def _comput_percentage(self, numerator, denominator):
        return float(numerator)/float(denominator) * 100

    # Create dynamic field responsible for counting number of actions "disagree"
    def stat_disagree(self, obj):
        num, den = self._get_stats(obj, choices.ER_ACTION_DISAGREE)
        per = self._comput_percentage(num, den)
        return f"{num} ({per:.2f})"

    stat_disagree.short_description = _('Disagree (%)')

    # Create dynamic field responsible for counting number of actions "incapable_to_fix"
    def stat_incapable_to_fix(self, obj):
        num, den = self._get_stats(obj, choices.ER_ACTION_INCAPABLE_TO_FIX)
        per = self._comput_percentage(num, den)
        return f"{num} ({per:.2f})"

    stat_incapable_to_fix.short_description = _('Incapable to fix (%)')


class ValidationErrorAdmin(ModelAdmin):
    model = ValidationError
    permission_helper_class = UploadPermissionHelper
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
        'package__file',
    )
    inspect_view_fields = {
        'package',
        'category',
        'message',
    }


class UploadModelAdmin(ModelAdminGroup):
    menu_icon = 'folder'
    menu_label = 'Upload'
    items = (PackageAdmin, QualityAnalystPackageAdmin, ValidationErrorAdmin)


modeladmin_register(UploadModelAdmin)


@hooks.register('register_admin_urls')
def register_disclosure_url():
    return [
        path('upload/',
        include('upload.urls', namespace='upload')),
    ]
