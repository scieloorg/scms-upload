import json
import logging
import os
import sys

from celery.result import AsyncResult
from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from packtools.sps import exceptions as sps_exceptions
from packtools.sps.models import package as sps_package
from packtools.sps.models.article_assets import ArticleAssets
from packtools.sps.models.article_renditions import ArticleRenditions
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre
from packtools.sps.utils import file_utils as sps_file_utils
from packtools.sps.validation import article as sps_validation_article
from packtools.sps.validation import journal as sps_validation_journal
from packtools.sps.validation.xml_structure import StructureValidator

from article import choices as article_choices
from article.models import Article
from collection import choices as collection_choices
from config import celery_app
from issue.models import Issue
from journal.models import Journal
from libs.dsm.publication.documents import get_document, get_similar_documents
from publication.tasks import task_publish_article
from tracker.models import UnexpectedEvent
from upload import choices
from upload.models import Package, ValidationReport

from . import choices, controller, exceptions
from .utils import file_utils, package_utils, xml_utils

User = get_user_model()


# @celery_app.task(name="Validate article change")
# def task_validate_article_change(
#     new_package_file_path, new_package_category, article_id
# ):
#     last_valid_pkg = controller.get_last_package(
#         article_id=article_id,
#         status=choices.PS_PUBLISHED,
#         category=choices.PC_SYSTEM_GENERATED,
#     )
#     last_valid_pkg_file_path = file_utils.get_file_absolute_path(
#         last_valid_pkg.file.name
#     )

#     if new_package_category == choices.PC_UPDATE:
#         task_validate_article_update.apply_async(
#             kwargs={
#                 "new_package_file_path": new_package_file_path,
#                 "last_valid_package_file_path": last_valid_pkg_file_path,
#             }
#         )
#     elif new_package_category == choices.PC_ERRATUM:
#         task_result_ae = task_validate_article_erratum.apply_async(
#             kwargs={"file_path": new_package_file_path}
#         )
#         task_result_cp = task_compare_packages.apply_async(
#             kwargs={
#                 "package1_file_path": new_package_file_path,
#                 "package2_file_path": last_valid_pkg_file_path,
#             }
#         )
#         task_update_article_status_by_validations.apply_async(
#             kwargs={
#                 "task_id_article_erratum": task_result_ae.id,
#                 "task_id_compare_packages": task_result_cp.id,
#                 "article_id": article_id,
#             }
#         )


# @celery_app.task(name="Update article status by validations")
# def task_update_article_status_by_validations(
#     task_id_article_erratum, task_id_compare_packages, article_id
# ):
#     ar_article_erratum = AsyncResult(task_id_article_erratum)
#     ar_compare_packages = AsyncResult(task_id_compare_packages)

#     while not ar_article_erratum.ready() or not ar_compare_packages.ready():
#         ...

#     if ar_article_erratum.result and ar_compare_packages.result:
#         update_article(article_id, status=AS_CHANGE_SUBMITTED)
#         return True

#     return False


# @celery_app.task(name="Validate article update")
# def task_validate_article_update(new_package_file_path, last_valid_package_file_path):
#     new_pkg_xmltree = sps_package.PackageArticle(new_package_file_path).xmltree_article
#     last_valid_pkg_xmltree = sps_package.PackageArticle(
#         last_valid_package_file_path
#     ).xmltree_article

#     return sps_validation_article.are_similar_articles(
#         new_pkg_xmltree, last_valid_pkg_xmltree
#     )


# @celery_app.task(name="Validate article erratum")
# def task_validate_article_erratum(file_path):
#     return sps_package.PackageWithErrata(file_path).is_valid()


# @celery_app.task(name="Compare packages")
# def task_compare_packages(package1_file_path, package2_file_path):
#     pkg1_xmltree = sps_package.PackageWithErrata(package1_file_path).xmltree_article
#     pkg2_xmltree = sps_package.PackageArticle(package2_file_path).xmltree_article

#     return sps_validation_article.are_similar_articles(pkg1_xmltree, pkg2_xmltree)


@celery_app.task(priority=0)
def task_optimise_package(file_path):
    source = file_utils.get_file_absolute_path(file_path)
    target = file_utils.generate_filepath_with_new_extension(source, ".optz", True)
    package_utils.optimise_package(source, target)
    package_utils.unzip(target)

    return target


@celery_app.task(priority=0)
def task_validate_assets(package_id, xml_path, package_files, xml_assets):

    has_errors = False
    package = Package.objects.get(pk=package_id)

    report = ValidationReport.create_or_update(
        package.creator, package, _("Assets Report"), choices.VAL_CAT_ASSET, True
    )

    for asset in xml_assets:
        is_present = asset["name"] in package_files
        asset.update({"xml_path": xml_path})

        if not is_present:
            has_errors = True
            validation_result = report.add_validation_result(
                status=choices.VALIDATION_RESULT_CRITICAL,
                message=f'{asset["name"]} {_("file is mentioned in the XML but not present in the package.")}',
                data=asset,
                subject=asset["name"],
            )

    if not has_errors:
        validation_result = report.add_validation_result(
            status=choices.VALIDATION_RESULT_SUCCESS,
            message=_("Package has all the expected asset files"),
            data=list(xml_assets),
            subject=_("assets"),
        )

    report.finish_validations()
    # devido às tarefas serem executadas concorrentemente,
    # necessário verificar se todas tarefas finalizaram e
    # então finalizar o pacote
    package.finish_validations()
    if package.is_approved:
        task_process_approved_package.apply_async(
            kwargs=dict(package_id=package.id, package_status=package.status)
        )


@celery_app.task(priority=0)
def task_validate_renditions(package_id, xml_path, package_files, xml_renditions):

    has_errors = False
    package = Package.objects.get(pk=package_id)

    report = ValidationReport.create_or_update(
        package.creator,
        package,
        _("Renditions Report"),
        choices.VAL_CAT_RENDITION,
        True,
    )

    for xml_rendition in xml_renditions:
        is_present = xml_rendition["name"] in package_files
        if not is_present:
            has_errors = True
            validation_result = report.add_validation_result(
                status=choices.VALIDATION_RESULT_FAILURE,
                message=f'{xml_rendition["lang"]} {_("language is mentioned in the XML but its PDF file not present in the package.")}',
                data=xml_rendition,
                subject=xml_rendition["lang"],
            )

    if not has_errors:
        validation_result = report.add_validation_result(
            status=choices.VALIDATION_RESULT_SUCCESS,
            message=_("Package has all the expected rendition files"),
            data=list(xml_renditions),
            subject=_("Renditions"),
        )

    report.finish_validations()
    package.finish_validations()
    # devido às tarefas serem executadas concorrentemente,
    # necessário verificar se todas tarefas finalizaram e
    # então finalizar o pacote
    if package.is_approved:
        task_process_approved_package.apply_async(
            kwargs=dict(package_id=package.id, package_status=package.status)
        )


@celery_app.task(bind=True, priority=0)
def task_validate_original_zip_file(
    self, package_id, file_path, journal_id, issue_id, article_id
):

    for xml_with_pre in XMLWithPre.create(path=file_path):
        xml_path = xml_with_pre.filename
        name, ext = os.path.splitext(xml_path)
        logging.info(f"xmlpre: {xml_with_pre.xmlpre}")
        package = Package.objects.get(pk=package_id)
        package.name = xml_with_pre.sps_pkg_name
        package.save()

        # FIXME nao usar o otimizado neste momento
        optimised_filepath = task_optimise_package(file_path)

        for optimised_xml_with_pre in XMLWithPre.create(path=optimised_filepath):

            package_files = optimised_xml_with_pre.filenames

            # Aciona validação de Assets
            task_validate_assets.apply_async(
                kwargs={
                    "package_id": package_id,
                    "xml_path": xml_path,
                    "package_files": package_files,
                    "xml_assets": list(optimised_xml_with_pre.assets),
                },
            )

            # Aciona validação de Renditions
            task_validate_renditions.apply_async(
                kwargs={
                    "package_id": package_id,
                    "xml_path": xml_path,
                    "package_files": package_files,
                    "xml_renditions": list(optimised_xml_with_pre.renditions),
                },
            )

            task_validate_xml_structure.apply_async(
                kwargs={
                    "file_path": file_path,
                    "xml_path": xml_path,
                    "package_id": package_id,
                    "journal_id": journal_id,
                    "issue_id": issue_id,
                    "article_id": article_id,
                },
            )

            # Aciona validacao do conteudo do XML
            task_validate_xml_content.apply_async(
                kwargs={
                    "file_path": file_path,
                    "xml_path": xml_path,
                    "package_id": package_id,
                    "journal_id": journal_id,
                    "issue_id": issue_id,
                    "article_id": article_id,
                },
            )


@celery_app.task(bind=True, priority=0)
def task_validate_xml_structure(
    self, file_path, xml_path, package_id, journal_id, issue_id, article_id
):
    # TODO REFATORAR
    # TODO levar este código para o packtools / XMLWithPre
    package = Package.objects.get(pk=package_id)
    for xml_with_pre in XMLWithPre.create(path=file_path):
        # {'is_valid': True,
        #    'errors_number': 0,
        #    'doctype_validation_result': [],
        #    'dtd_is_valid': True,
        #    'dtd_errors': [],
        #    'style_is_valid': True,
        #    'style_errors': []}
        sv = StructureValidator(xml_with_pre)
        summary = sv.validate()

        report = ValidationReport.create_or_update(
            package.creator, package, _("DTD Report"), choices.VAL_CAT_XML_FORMAT, True
        )
        for item in summary["dtd_errors"]:
            validation_result = report.add_validation_result(
                status=choices.VALIDATION_RESULT_CRITICAL,
                message=item["message"],
                data={
                    "apparent_line": item.get("apparent_line"),
                    "message": item["message"],
                },
            )
        if summary["dtd_is_valid"]:
            validation_result = report.add_validation_result(
                status=choices.VALIDATION_RESULT_SUCCESS,
                message=_("No error found"),
            )
        report.finish_validations()

        report = ValidationReport.create_or_update(
            package.creator,
            package,
            _("Style checker Report"),
            choices.VAL_CAT_STYLE,
            True,
        )
        for item in summary["style_errors"]:
            validation_result = report.add_validation_result(
                status=choices.VALIDATION_RESULT_FAILURE,
                message=item.message,
                data={
                    "apparent_line": item.line,
                    "label": item.label,
                    "level": item.level,
                },
            )
        if summary["style_is_valid"]:
            validation_result = report.add_validation_result(
                status=choices.VALIDATION_RESULT_SUCCESS,
                message=_("No error found"),
            )
        report.finish_validations()
        # devido às tarefas serem executadas concorrentemente,
        # necessário verificar se todas tarefas finalizaram e
        # então finalizar o pacote
        package.finish_validations()
        if package.is_approved:
            task_process_approved_package.apply_async(
                kwargs=dict(package_id=package.id)
            )


@celery_app.task(bind=True, priority=0)
def task_validate_xml_content(
    self, file_path, xml_path, package_id, journal_id, issue_id, article_id
):
    try:
        package = Package.objects.get(pk=package_id)
        if journal_id:
            journal = Journal.objects.get(pk=journal_id)
        else:
            journal = None

        if issue_id:
            issue = Issue.objects.get(pk=issue_id)
        else:
            issue = None

        controller.validate_xml_content(package, journal)

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "operation": "upload.tasks.task_validate_xml_content",
                "detail": dict(file_path=file_path, xml_path=xml_path),
            },
        )


@celery_app.task(bind=True, priority=0)
def task_process_approved_package(
    self,
    package_id,
    user_id=None,
):
    package = Package.objects.get(pk=package_id)
    package.process_approved_package(user=User.objects.get(pk=user_id))
    task_publish_article.apply_async(
        kwargs=dict(
            user_id=user_id,
            username=None,
            api_data=None,
            website_kind=collection_choices.QA,
            upload_package_id=package.id,
        )
    )
