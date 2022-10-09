from datetime import datetime

from django.shortcuts import get_object_or_404

from collection.models import NewWebSiteConfiguration
from libs.dsm.publication.db import mk_connection, exceptions

from .models import ErrorResolution, ErrorResolutionOpinion, Package, ValidationError, choices


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
    er = upsert_object(ErrorResolution, validation_error_id, user)
    er.action = action
    er.comment = comment
    er.validation_error = ValidationError.objects.get(pk=validation_error_id)
    er.save()


def upsert_validation_error_resolution_opinion(validation_error_id, user, opinion, comment):
    ero = upsert_object(ErrorResolutionOpinion, validation_error_id, user)

    ero.opinion = opinion
    ero.comment = comment
    ero.validation_error = ValidationError.objects.get(pk=validation_error_id)

    ero.save()


def upsert_object(object_class, validation_error_id, user):
    try:
        obj_instance = object_class.objects.get(pk=validation_error_id)
        obj_instance.updated = datetime.now()
        obj_instance.updated_by = user
    except object_class.DoesNotExist:
        obj_instance = object_class()
        obj_instance.creator = user
        obj_instance.created = datetime.now()

    return obj_instance


def update_package_check_finish(package_id):
    package = get_object_or_404(Package, pk=package_id)

    if package.status == choices.PS_READY_TO_BE_FINISHED:
        package.status = choices.PS_QA
        package.save()
        return True

    return False


def update_package_check_errors(package_id):
    package = get_object_or_404(Package, pk=package_id)

    for ve in package.validationerror_set.all():
        action = ve.resolution.action
        if action in (choices.ER_ACTION_TO_FIX, ''):
            package.status = choices.PS_PENDING_CORRECTION    
            package.save()

            return package.status

    package.status = choices.PS_READY_TO_BE_FINISHED
    package.save()

    return package.status


def update_package_check_opinions(package_id):
    package = get_object_or_404(Package, pk=package_id)

    for ve in package.validationerror_set.all():
        opinion = ve.analysis.opinion
        if opinion in (choices.ER_OPINION_FIX_DEMANDED, ''):
            package.status = choices.PS_PENDING_CORRECTION
            package.save()

            return package.status

    package.status = choices.PS_ACCEPTED
    package.save()

    return package.status


def create_package(article_id, user_id, file_name, category=choices.PC_SYSTEM_GENERATED, status=choices.PS_PUBLISHED):
    package = Package()
    package.article_id = article_id
    package.creator_id = user_id
    package.created = datetime.utcnow()
    package.file = file_name
    package.category = category
    package.status = status

    package.save()

    return package


def get_last_package(article_id, **kwargs):
    try:
        return Package.objects.filter(article=article_id, **kwargs).order_by('-created').first()
    except Package.DoesNotExist:
        return 


def establish_site_connection(url='scielo.br'):
    try:
        host = NewWebSiteConfiguration.objects.get(url__icontains=url).db_uri
    except NewWebSiteConfiguration.DoesNotExist:
        return False

    try:
        mk_connection(host=host)
    except exceptions.DBConnectError:
        return False

    return True


def compute_package_validation_error_resolution_stats(package_id):
    try:
        obj = Package.objects.get(pk=package_id)
    except Package.DoesNotExist:
        return

    def _get_percentage(numerator, denominator):
        return float(numerator)/float(denominator) * 100

    def _get_n(value, validation_error_resolution_list):
        return len([o for o in validation_error_resolution_list if o.action == value])

    ver_list = [ve.resolution for ve in obj.validationerror_set.all()]
    den = len(ver_list)

    disagree_num = _get_n(choices.ER_ACTION_DISAGREE, ver_list)
    disagree_per = _get_percentage(disagree_num, den)
    obj.stat_disagree_n = disagree_num
    obj.stat_disagree_p = disagree_per

    incapable_num = _get_n(choices.ER_ACTION_INCAPABLE_TO_FIX, ver_list)
    incapable_per = _get_percentage(incapable_num, den)
    obj.stat_incapable_to_fix_n = incapable_num
    obj.stat_incapable_to_fix_p = incapable_per

    obj.save()
