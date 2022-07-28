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


def reject(request):
    """
    This view function abilitates the user to reject a package through the graphic-interface.

    When a user clicks the "reject" button, the package state changes to "reject".
    """
    package_id = request.GET.get("package_id", None)
    
    if package_id:
        package = get_object_or_404(Package, pk=package_id)

    if request.method == 'GET':
        package.status = PackageStatus.REJECTED
        package.updated_by = request.user
        package.save()
        messages.success(request, _("Package was rejected."))

    return redirect(request.META.get('HTTP_REFERER'))


def validate(request):
    """
    This view function abilitates the user to schedule the package validation.
    
    When a user clicks the "validate" button, the package state changes to "enqueued_for_validation".
    
    TODO: This function must be a task.
    """
    package_id = request.GET.get("package_id", None)
    
    if package_id:
        package = get_object_or_404(Package, pk=package_id)

    if request.method == 'GET':
        package.status = PackageStatus.ENQUEUED_FOR_VALIDATION
        package.updated_by = request.user
        package.save()
        messages.success(request, _("Package enqueued for validation."))

    return redirect(request.META.get('HTTP_REFERER'))
