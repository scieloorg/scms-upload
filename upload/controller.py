from django.shortcuts import get_object_or_404

from .models import Package, ValidationError


def add_validation_error(error_category, package_id, package_status, row=None, column=None, message=None):
    ve = ValidationError()
    ve.category = error_category

    ve.package = get_object_or_404(Package, pk=package_id)
    ve.package.status = package_status
    ve.row = row
    ve.column = column
    ve.message = message

    ve.package.save()
    ve.save()
