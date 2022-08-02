from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _

from wagtail.admin import messages

from .choices import PackageStatus
from .models import Package


def finish_deposit(request):
    """
    This view function abilitates the user to finish deposit of a package through the graphic-interface.

    When a user clicks the "finish deposit" button, the package state changes to "finished".
    """
    package_id = request.GET.get("package_id", None)
    
    if package_id:
        package = get_object_or_404(Package, pk=package_id)

    if request.method == 'GET':
        package.status = PackageStatus.FINISHED
        package.updated_by = request.user
        package.save()
        messages.success(request, _("Package was finished."))

    return redirect(request.META.get('HTTP_REFERER'))
