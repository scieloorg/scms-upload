from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from .models import Package, choices
from .utils.package_utils import (coerce_package_and_errors, render_html)


def finish_deposit(request):
    """
    This view function abilitates the user to finish deposit of a package through the graphic-interface.

    TODO: 
    """
    return redirect(request.META.get('HTTP_REFERER'))


def preview_document(request):
    """
    This view function abilitates the user to see a preview of HTML
    """
    package_id = request.GET.get('package_id')

    if package_id:
        package = get_object_or_404(Package, pk=package_id)

        document_html = render_html(package.file.name)

        return render(
                request=request,
                template_name='modeladmin/upload/package/preview_document.html',
                context={'document': document_html},
            )

    return redirect(request.META.get('HTTP_REFERER'))


def validation_report(request):
    """
    This view function abilitates the user to see a validation report.
    """
    package_id = request.GET.get('package_id')
    report_category_name = request.GET.get('category')

    if package_id:
        package = get_object_or_404(Package, pk=package_id)

        if report_category_name == 'asset-and-rendition-error':
            validation_errors = package.validationerror_set.filter(category__in=set(['asset-error', 'rendition-error']))

            assets, renditions = coerce_package_and_errors(package, validation_errors)

            return render(
                request=request,
                template_name='modeladmin/upload/package/validation_report/digital_assets_and_renditions.html',
                context={
                    'package_inspect_url': request.META.get('HTTP_REFERER'),
                    'report_title': _('Digital Assets and Renditions Report'),
                    'report_subtitle': package.file.name,
                    'assets': assets,
                    'renditions': renditions,
                }
            )

    return redirect(request.META.get('HTTP_REFERER'))
