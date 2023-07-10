from datetime import datetime

from django.shortcuts import get_object_or_404

from article.controller import (
    request_pid_v3_and_create_article as article_controller_request_pid_v3_and_create_article,
)
from collection.models import NewWebSiteConfiguration
from libs.dsm.publication.db import exceptions, mk_connection
from xmlsps.xml_sps_lib import get_xml_items_from_zip_file

from .models import (
    ErrorResolution,
    ErrorResolutionOpinion,
    Package,
    ValidationResult,
    choices,
)


def add_validation_result(
    error_category, package_id, status=None, message=None, data=None
):
    val_res = ValidationResult()
    val_res.category = error_category

    val_res.package = get_object_or_404(Package, pk=package_id)
    val_res.status = status
    val_res.message = message
    val_res.data = data

    if val_res.status == choices.VS_DISAPPROVED:
        val_res.package.status = choices.PS_REJECTED
        val_res.package.save()

    val_res.save()
    return val_res


def update_validation_result(validation_result_id, **kwargs):
    try:
        val_res = ValidationResult.objects.get(pk=validation_result_id)
        for k, v in kwargs.items():
            setattr(val_res, k, v)

        if val_res.status == choices.VS_DISAPPROVED:
            val_res.package.status = choices.PS_REJECTED
            val_res.package.save()

        val_res.save()
    except ValidationResult.DoesNotExist:
        ...


def upsert_validation_result_error_resolution(
    validation_result_id, user, action, rationale
):
    er = upsert_object(ErrorResolution, validation_result_id, user)
    er.action = action
    er.rationale = rationale
    er.validation_result = ValidationResult.objects.get(pk=validation_result_id)
    er.save()


def upsert_validation_result_error_resolution_opinion(
    validation_result_id, user, opinion, guidance
):
    ero = upsert_object(ErrorResolutionOpinion, validation_result_id, user)
    ero.opinion = opinion
    ero.guidance = guidance
    ero.validation_result = ValidationResult.objects.get(pk=validation_result_id)
    ero.save()


def upsert_object(object_class, validation_result_id, user):
    try:
        obj_instance = object_class.objects.get(pk=validation_result_id)
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

    for vr in package.validationresult_set.filter(status=choices.VS_DISAPPROVED):
        if vr.resolution.action in (choices.ER_ACTION_TO_FIX, ""):
            package.status = choices.PS_PENDING_CORRECTION
            package.save()

            return package.status

    package.status = choices.PS_READY_TO_BE_FINISHED
    package.save()

    return package.status


def update_package_check_opinions(package_id):
    package = get_object_or_404(Package, pk=package_id)

    for vr in package.validationresult_set.filter(status=choices.VS_DISAPPROVED):
        opinion = vr.analysis.opinion
        if opinion in (choices.ER_OPINION_FIX_DEMANDED, ""):
            package.status = choices.PS_PENDING_CORRECTION
            package.save()

            return package.status

    package.status = choices.PS_ACCEPTED
    package.save()

    return package.status


def create_package(
    article_id,
    user_id,
    file_name,
    category=choices.PC_SYSTEM_GENERATED,
    status=choices.PS_PUBLISHED,
):
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
        return (
            Package.objects.filter(article=article_id, **kwargs)
            .order_by("-created")
            .first()
        )
    except Package.DoesNotExist:
        return


def establish_site_connection(url="scielo.br"):
    try:
        host = NewWebSiteConfiguration.objects.get(url__icontains=url).db_uri
    except NewWebSiteConfiguration.DoesNotExist:
        return False

    try:
        mk_connection(host=host)
    except exceptions.DBConnectError:
        return False

    return True


def request_pid_for_accepted_packages(user_id):
    user = User.objects.get(pk=user_id)
    for pkg in Package.objects.filter(
        status=choices.PS_ACCEPTED, article__isnull=True
    ).iterator():
        for xml_item in get_xml_items_from_zip_file(pkg.file.path):
            response = article_controller_request_pid_v3_and_create_article(
                xml_item["xml_with_pre"],
                xml_item["filename"],
                user=user,
            )
            try:
                pkg.article = response["article"]
                pkg.save()
            except KeyError:
                # TODO registrar em algum modelo os erros para que o usuário
                # fique ciente de que houve erro
                logging.exception(
                    f"Unable to create / update article {response['error_msg']}"
                )
