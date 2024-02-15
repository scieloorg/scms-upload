import logging
from datetime import datetime

from django.shortcuts import get_object_or_404

from article.controller import create_article
from collection.models import WebSiteConfiguration
from libs.dsm.publication.db import exceptions, mk_connection
from package import choices as package_choices
from package.models import SPSPkg

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
    package = get_object_or_404(Package, pk=package_id)
    return package.add_validation_result(
        error_category, status, message, data,
    )


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
        host = WebSiteConfiguration.objects.get(url__icontains=url).db_uri
    except WebSiteConfiguration.DoesNotExist:
        return False

    try:
        mk_connection(host=host)
    except exceptions.DBConnectError:
        return False

    return True


def request_pid_for_accepted_packages(user):
    # FIXME Usar package.SPSPkg no lugar de Package
    for pkg in Package.objects.filter(
        status=choices.PS_ACCEPTED, article__isnull=True
    ).iterator():
        # FIXME indicar se é atualização (True) ou novo (False)
        is_published = None

        sps_pkg = SPSPkg.create_or_update(
            user,
            pkg.file.path,
            package_choices.PKG_ORIGIN_INGRESS_WITH_VALIDATION,
            reset_failures=True,
            is_published=is_published,
        )

        response = create_article(user, sps_pkg)
        try:
            pkg.article = response["article"]
            pkg.save()
        except KeyError:
            # TODO registrar em algum modelo os erros para que o usuário
            # fique ciente de que houve erro
            logging.exception(
                f"Unable to create / update article {response['error_msg']}"
            )
