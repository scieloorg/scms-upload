from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext as _

from config.menu import get_menu_order

from wagtail.core import hooks
from wagtail.contrib.modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from wagtail.contrib.modeladmin.views import CreateView, InspectView

from article.models import Article
from issue.models import Issue

from .button_helper import UploadButtonHelper
from .models import choices, Package, QAPackage, ValidationError
from .permission_helper import UploadPermissionHelper
from .tasks import run_validations
from .utils import package_utils


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
        article_id = self.request.POST.get('article')
        try:
            article = Article.objects.get(pk=article_id)
        except Article.DoesNotExist:
            article = None

        issue_id = self.request.POST.get('issue')
        try:
            issue = Issue.objects.get(pk=issue_id)
        except Issue.DoesNotExist:
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
    def get_context_data(self):
        data = {
            'validation_errors': {},
            'package_id': self.instance.id,
            'status': self.instance.status,
            'category': self.instance.category,
            'languages': package_utils.get_languages(self.instance.file.name),
        }

        for ve in self.instance.validationerror_set.all():
            vek = ve.report_name()
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
        'stat_disagree',
        'stat_incapable_to_fix',
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

    def stat_incapable_to_fix(self, obj):
        if obj.stat_incapable_to_fix_n:
            return f"{obj.stat_incapable_to_fix_n} ({obj.stat_incapable_to_fix_p}%)"
        return '-'

    def stat_disagree(self, obj):
        if obj.stat_disagree_n:
            return f"{obj.stat_disagree_n} ({obj.stat_disagree_p}%)"
        return '-'

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


class UploadModelAdminGroup(ModelAdminGroup):
    menu_icon = 'folder'
    menu_label = 'Upload'
    items = (PackageAdmin, QualityAnalystPackageAdmin, ValidationErrorAdmin)
    menu_order = get_menu_order('upload')


modeladmin_register(UploadModelAdminGroup)


@hooks.register('register_admin_urls')
def register_disclosure_url():
    return [
        path('upload/',
        include('upload.urls', namespace='upload')),
    ]
