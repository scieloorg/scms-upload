from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _

from wagtail.admin import messages

from .choices import PackageStatus
from .models import Package


def accept(request):
    """
    This view function abilitates the user to accept a package through the graphic-interface.

    When a user clicks the "accept" button, the package state changes to "accept".
    """
    package_id = request.GET.get("package_id", None)
    
    if package_id:
        package = get_object_or_404(Package, pk=package_id)

    if request.method == 'GET':
        package.status = PackageStatus.ACCEPTED
        package.updated_by = request.user
        package.save()
        messages.success(request, _("Package was accepted."))

    return redirect(request.META.get('HTTP_REFERER'))
