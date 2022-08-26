from datetime import datetime

from django.shortcuts import get_object_or_404

from .models import ErrorResolution, Package, ValidationError, choices


def add_validation_error(error_category, package_id, package_status, message=None, data=None):
    ve = ValidationError()
    ve.category = error_category

    ve.package = get_object_or_404(Package, pk=package_id)
    ve.package.status = package_status
    ve.message = message
    ve.data = data

    ve.package.save()
    ve.save()


def upsert_validation_error_resolution(validation_error_id, user, action, comment):
    ve = ValidationError.objects.get(pk=validation_error_id)

    try:
        er = ErrorResolution.objects.get(pk=validation_error_id)
        er.updated = datetime.now()
        er.updated_by = user
    except ErrorResolution.DoesNotExist:
        er = ErrorResolution()
        er.creator = user
        er.created = datetime.now()

    er.action = action
    er.comment = comment
    er.validation_error = ve
    
    er.save()

    return er

