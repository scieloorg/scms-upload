from django.http import JsonResponse
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from upload.forms import ValidationResultErrorResolutionForm, ValidationResultErrorResolutionOpinionForm

from .controller import (
    upsert_validation_result_error_resolution, 
    update_package_check_finish,
    upsert_validation_result_error_resolution_opinion,
)
from .models import Package, choices
from .tasks import check_resolutions, check_opinions
from .utils.package_utils import coerce_package_and_errors, render_html


def ajx_error_resolution(request):
    """
    This function view enables the system to save error-resolution data through Ajax requests.
    """
    if request.method == 'POST':
        scope = request.POST.get('scope')
        data = ValidationResultErrorResolutionOpinionForm(request.POST) if scope == 'analyse' else ValidationResultErrorResolutionForm(request.POST)

        kwargs = {
            'validation_result_id': data['validation_result_id'].value(),
            'user': request.user,
            'comment': data['comment'].value(),
        }

        if data.is_valid():
            if scope == 'analyse':
                kwargs.update({'opinion': data['opinion'].value()})
                upsert_validation_result_error_resolution_opinion(**kwargs)
            else: 
                kwargs.update({'action': data['action'].value()})
                upsert_validation_result_error_resolution(**kwargs)

        return JsonResponse({'status': 'success'})


def error_resolution(request):
    """
    This view function enables the user to:
     1. POST: update package status according to error resolution
     2. GET: list error resolution objects related to a package
    """
    if request.method == 'POST':
        package_id = request.POST.get('package_id')
        scope = request.POST.get('scope', '')

        if package_id:
            check_opinions(package_id) if scope == 'analyse' else check_resolutions(package_id)

        messages.success(request, _('Thank you for submitting your responses.'))

        return redirect(f'/admin/upload/package/inspect/{package_id}')

    if request.method == 'GET':
        package_id = request.GET.get('package_id')
        scope = request.GET.get('scope')

        if package_id:
            package = get_object_or_404(Package, pk=package_id)

            if package.status != choices.PS_REJECTED:
                validation_results = package.validationresult_set.filter(status=choices.VS_DISAPPROVED)

                template_type = 'start' if scope not in ('analyse', 'report') else scope

                return render(
                    request=request,
                    template_name=f'modeladmin/upload/package/error_resolution/index/{template_type}.html',
                    context={
                        'package_id': package_id,
                        'package_inspect_url': request.META.get('HTTP_REFERER'),
                        'report_title': _('Errors Resolution'),
                        'report_subtitle': package.file.name,
                        'validation_results': validation_results,
                    }
                )
            else:
                messages.warning(request, _('It is not possible to see the Error Resolution page for a rejected package.'))

    return redirect(request.META.get('HTTP_REFERER'))


def finish_deposit(request):
    """
    This view function enables the user to finish deposit of a package through the graphic-interface.
    """
    package_id = request.GET.get('package_id')

    if package_id:
        can_be_finished = update_package_check_finish(package_id)

        if can_be_finished:
            messages.success(request, _('Package has been submitted to QA'))
        else:
            messages.warning(request, _('Package could not be submitted to QA due to validation errors. Go to Error Resolution page for more details.'))

    return redirect(f'/admin/upload/package/inspect/{package_id}')


def preview_document(request):
    """
    This view function enables the user to see a preview of HTML
    """
    package_id = request.GET.get('package_id')

    if package_id:
        package = get_object_or_404(Package, pk=package_id)
        language = request.GET.get('language')
        xml_path = request.GET.get('xml_path')

        document_html = render_html(package.file.name, xml_path, language)

        for vr in package.validationresult_set.all():
            if vr.report_name() == choices.VR_XML_OR_DTD and vr.status == choices.VS_DISAPPROVED:
                messages.error(request, _('It is not possible to preview HTML of an invalid XML.'))
                return redirect(request.META.get('HTTP_REFERER'))

        return render(
            request=request,
            template_name='modeladmin/upload/package/preview_document.html',
            context={'document': document_html, 'package_status': package.status},
        )

    return redirect(request.META.get('HTTP_REFERER'))


def validation_report(request):
    """
    This view function enables the user to see a validation report.
    """
    package_id = request.GET.get('package_id')
    report_name = request.GET.get('report')

    if package_id:
        package = get_object_or_404(Package, pk=package_id)

        context = {
            'package_inspect_url': request.META.get('HTTP_REFERER'),
            'report_subtitle': package.file.name,
        }

        vrs = package.validationresult_set.filter(category__in=choices.VALIDATION_REPORT_ITEMS[report_name])

        if report_name == choices.VR_INDIVIDUAL_CONTENT:
            context.update({
                'report_title': _('Individual Content Report'),
                'content_errors':  vrs,
            })
            return render(
                request=request,
                template_name='modeladmin/upload/package/validation_report/individual_content.html',
                context=context
            )

        if report_name == choices.VR_ASSET_AND_RENDITION:
            assets, renditions = coerce_package_and_errors(package, vrs.filter(status=choices.VS_DISAPPROVED))
            context.update({
                'report_title': _('Digital Assets and Renditions Report'),
                'assets': assets,
                'renditions': renditions,
            })
            return render(
                request=request,
                template_name='modeladmin/upload/package/validation_report/digital_assets_and_renditions.html',
                context=context
            )

    return redirect(request.META.get('HTTP_REFERER'))


def assign(request):
    package_id = request.GET.get('package_id')
    user = request.user

    if not user.has_perm('upload.assign_package'):
        messages.error(
            request,
            _('You do have permission to assign packages.')
        )
    elif package_id:
        package = get_object_or_404(Package, pk=package_id)

        if package.assignee is None:
            package.assignee = user
            package.save()

            messages.success(
                request,
                _('Package has been assigned with success.')
            )
        else:
            messages.error(
                request,
                _('It was not possible to assign the package because it already has an assinee.')
            )

    return redirect(request.META.get('HTTP_REFERER'))
