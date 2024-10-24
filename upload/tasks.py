import json
import logging
import os
import sys

from celery.result import AsyncResult
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre
from packtools.sps.validation.xml_structure import StructureValidator
from packtools.utils import SPPackage

from article import choices as article_choices
from article.models import Article
from collection import choices as collection_choices
from config import celery_app
from issue.models import Issue
from journal.models import Journal
from publication.tasks import task_publish_article
from tracker.models import UnexpectedEvent
from upload import choices
from upload.controller import receive_package
from upload.models import Package, ValidationReport, PackageZip
from upload.validation.rendition_validation import validate_rendition
from upload.validation.html_validation import validate_webpage

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
    package.finish_validations(task_process_qa_decision)
    # if package.is_approved:
    #     task_process_approved_package.apply_async(
    #         kwargs=dict(package_id=package.id, package_status=package.status)
    #     )


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
    package.finish_validations(task_process_qa_decision)
    # devido às tarefas serem executadas concorrentemente,
    # necessário verificar se todas tarefas finalizaram e
    # então finalizar o pacote
    # if package.is_approved:
    #     task_process_approved_package.apply_async(
    #         kwargs=dict(package_id=package.id, package_status=package.status)
    #     )


@celery_app.task(priority=0)
def task_validate_renditions_content(package_id, xml_path):

    package = Package.objects.get(pk=package_id)

    report = ValidationReport.create_or_update(
        package.creator,
        package,
        _("Renditions content report"),
        choices.VAL_CAT_RENDITION_CONTENT,
        True,
    )
    try:

        for rendition in package.renditions:
            for result in validate_rendition(rendition, package.xml_with_pre):
                validation_result = report.add_validation_result(
                    status=choices.VALIDATION_RESULT_FAILURE,
                    message=result["message"],
                    data={
                        "filename": rendition["name"],
                        "lang": rendition["lang"]},
                    subject=rendition["name"],
                )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "operation": "upload.tasks.task_validate_renditions_content",
                "detail": dict(xml_path=xml_path),
            },
        )
    report.finish_validations()
    package.finish_validations(task_process_qa_decision)


@celery_app.task(bind=True, priority=0)
def task_receive_packages(
    self, user_id, pkg_zip_id
):
    logging.info(f"user_id: {user_id}")
    logging.info(f"pkg_zip_id: {pkg_zip_id}")
    user = User.objects.get(pk=user_id)
    pkg_zip = PackageZip.objects.get(pk=pkg_zip_id)

    for item in pkg_zip.split(user):
        try:
            logging.info(str(item))
            task_receive_package.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    pkg_id=item["package"].id,
                )
            )
        except Exception as exc:
            logging.exception(exc)
            continue


@celery_app.task(bind=True, priority=0)
def task_receive_package(
    self, user_id, pkg_id
):
    logging.info(f"user_id: {user_id}")
    logging.info(f"pkg_id: {pkg_id}")
    user = User.objects.get(pk=user_id)
    package = Package.objects.get(pk=pkg_id)

    response = receive_package(user, package)
    logging.info(response)
    if response.get("error_level") != choices.VALIDATION_RESULT_BLOCKING:
        task_validate_original_zip_file.apply_async(
            kwargs=dict(
                package_id=package.id,
                file_path=package.file.path,
                journal_id=response["journal"].id,
                issue_id=response["issue"].id,
                article_id=package.article and package.article.id or None,
            )
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

            # Aciona validação do conteúdo de Renditions
            task_validate_renditions_content.apply_async(
                kwargs={
                    "package_id": package_id,
                    "xml_path": xml_path,
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

        try:
            sv = StructureValidator(xml_with_pre)
            summary = sv.validate()
        except Exception as exc:
            logging.exception(exc)
            return

        report = ValidationReport.create_or_update(
            package.creator, package, _("DTD Report"), choices.VAL_CAT_XML_FORMAT, True
        )
        try:
            for item in summary["dtd_errors"]:
                validation_result = report.add_validation_result(
                    status=choices.VALIDATION_RESULT_CRITICAL,
                    message=item.message,
                    data={
                        "apparent_line": item.line,
                        "message": item.message,
                    },
                )
            if summary["dtd_is_valid"]:
                validation_result = report.add_validation_result(
                    status=choices.VALIDATION_RESULT_SUCCESS,
                    message=_("No error found"),
                )
        except Exception as exc:
            logging.exception(f"{exc}: {summary}")
            validation_result = report.add_validation_result(
                status=choices.VALIDATION_RESULT_CRITICAL,
                message=str(exc),
                data=str(summary),
            )

        report.finish_validations()

        report = ValidationReport.create_or_update(
            package.creator,
            package,
            _("Style checker Report"),
            choices.VAL_CAT_STYLE,
            True,
        )

        try:
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
        except Exception as exc:
            logging.exception(f"{exc}: {summary}")
            validation_result = report.add_validation_result(
                status=choices.VALIDATION_RESULT_CRITICAL,
                message=str(exc),
                data=str(summary),
            )

        report.finish_validations()

        # devido às tarefas serem executadas concorrentemente,
        # necessário verificar se todas tarefas finalizaram e
        # então finalizar o pacote
        package.finish_validations(task_process_qa_decision)
        # if package.is_approved:
        #     task_process_approved_package.apply_async(
        #         kwargs=dict(package_id=package.id)
        #     )


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

        if controller.validate_xml_content(package, journal):
            package.finish_validations(task_process_qa_decision)

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
def task_process_qa_decision(
    self,
    user_id,
    package_id,
):
    user = User.objects.get(pk=user_id)
    package = Package.objects.get(pk=package_id)
    websites = package.process_qa_decision(user)

    logging.info(f"Process qa decision. Publish on {websites}")

    if websites and "QA" in websites:
        task_publish_article.apply_async(
            kwargs=dict(
                user_id=user.id,
                username=user.username,
                api_data=None,
                website_kind="QA",
                article_proc_id=None,
                upload_package_id=package.id,
            )
        )
    if websites and "PUBLIC" in websites:
        task_publish_article.apply_async(
            kwargs=dict(
                user_id=user.id,
                username=user.username,
                api_data=None,
                website_kind="PUBLIC",
                article_proc_id=None,
                upload_package_id=package.id,
            )
        )
        for item in package.linked.all():
            task_publish_article.apply_async(
                kwargs=dict(
                    user_id=user.id,
                    username=user.username,
                    api_data=None,
                    website_kind="PUBLIC",
                    article_proc_id=None,
                    upload_package_id=item.id,
                )
            )

    # if package.qa_decision == choices.PS_PUBLISHED:
    #     messages.success(request, _("Package {} is published").format(package))
    # elif package.qa_decision == choices.PS_READY_TO_PUBLISH:
    #     for item in package.pkg_zip.packages.all():
    #         if item.qa_decision == choices.PS_READY_TO_PUBLISH:
    #             messages.success(request, _("Package {} is ready to publish").format(item))
    #         else:
    #             messages.warning(
    #                 request,
    #                 _("Package {} is not ready to publish ({})").format(item, item.qa_decision))


@celery_app.task(priority=0)
def task_validate_webpages_content(package_id):

    package = Package.objects.get(pk=package_id)

    report = ValidationReport.create_or_update(
        package.creator,
        package,
        _("Web page Report"),
        choices.VAL_CAT_WEB_PAGE_CONTENT,
        True,
    )
    try:

        for webpage in package.htmls:
            for result in validate_webpage(webpage, package.xml_with_pre):
                validation_result = report.add_validation_result(
                    status=choices.VALIDATION_RESULT_FAILURE,
                    message=result["message"],
                    data={
                        "filename": webpage["name"],
                        "lang": webpage["lang"]},
                    subject=webpage["name"],
                )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "operation": "upload.tasks.task_validate_webpages_content",
                "detail": dict(package=str(package)),
            },
        )
    report.finish_validations()
    package.finish_validations(task_process_qa_decision)
