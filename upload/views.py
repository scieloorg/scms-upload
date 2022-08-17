from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from .models import Package
from .utils.package_utils import coerce_package_and_errors


def finish_deposit(request):
    """
    This view function abilitates the user to finish deposit of a package through the graphic-interface.

    TODO: 
    """
    return redirect(request.META.get('HTTP_REFERER'))


def validation_report(request):
    """
    This view function abilitates the user to see a validation report.
    """
    package_id = request.GET.get('package_id')
    report_category_name = request.GET.get('category')

    if package_id:
        package = get_object_or_404(Package, pk=package_id)

        validation_errors = package.validationerror_set.filter(category=report_category_name)

        assets = coerce_package_and_errors(package, validation_errors)
    
        if report_category_name == 'asset-error':
            return render(
                request=request,
                template_name='modeladmin/upload/package/validation_report/digital_assets.html',
                context={
                    'package_inspect_url': request.META.get('HTTP_REFERER'),
                    'report_title': _('Digital Assets Report'),
                    'report_subtitle': package.file.name,
                    'assets': assets,
                }
            )

    return redirect(request.META.get('HTTP_REFERER'))
