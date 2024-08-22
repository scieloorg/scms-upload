import logging
import sys
import traceback
from datetime import datetime
from zipfile import ZIP_DEFLATED, ZipFile

from django.utils.translation import gettext as _
from packtools.sps.models.front_articlemeta_issue import ArticleMetaIssue
from packtools.sps.models.journal_meta import ISSN, Title
from packtools.sps.pid_provider.xml_sps_lib import GetXMLItemsError, XMLWithPre

from article import choices as article_choices
from article.models import Article
from collection.models import WebSiteConfiguration
from core.utils.requester import fetch_data
from issue.models import Issue
from journal.models import Journal, OfficialJournal
from libs.dsm.publication.db import exceptions, mk_connection
from package import choices as package_choices
from package.models import SPSPkg
from pid_provider.requester import PidRequester
from proc.controller import create_or_update_journal, create_or_update_issue
from tracker.models import UnexpectedEvent
from upload import xml_validation
from upload.models import (
    Package,
    ValidationReport,
    XMLError,
    XMLErrorReport,
    XMLInfoReport,
    choices,
)
from upload.utils import file_utils, package_utils, xml_utils

pp = PidRequester()


class UnexpectedPackageError(Exception):
    ...


class PackageDataError(Exception):
    ...


def get_last_package(article_id, **kwargs):
    try:
        return (
            Package.objects.filter(article=article_id, **kwargs)
            .order_by("-created")
            .first()
        )
    except Package.DoesNotExist:
        return


def receive_package(request, package):
    try:
        zip_xml_file_path = package.file.path
        user = request.user
        response = {}
        for xml_with_pre in XMLWithPre.create(path=zip_xml_file_path):
            package.xml_name = xml_with_pre.filename
            package.save()

            response = _check_article_and_journal(xml_with_pre, user=user)
            logging.info(response)
            if response.get("xml_changed"):
                # atualiza conteúdo de zip
                with ZipFile(zip_xml_file_path, "a", compression=ZIP_DEFLATED) as zf:
                    zf.writestr(
                        xml_with_pre.filename,
                        xml_with_pre.tostring(pretty_print=True),
                    )

            package.article = response.get("article")
            package.issue = (
                response.get("issue") or package.article and package.article.issue
            )
            package.journal = (
                response.get("journal") or package.article and package.article.journal
            )
            package.category = response.get("package_category")
            package.status = response.get("package_status")
            package.expiration_date = response.get("previous_package")

            try:
                article_pubdate = xml_with_pre.article_publication_date
                article_pubdate = datetime.strptime(article_pubdate, "%Y-%m-%d")
            except Exception:
                article_pubdate = None

            package.xml_pubdate = article_pubdate
            package.save()

            error = (
                response.get("blocking_error")
                or not package.journal
                or not package.issue
            )
            if error:
                report = ValidationReport.create_or_update(
                    user=user,
                    package=package,
                    title=_("Package file"),
                    category=choices.VAL_CAT_PACKAGE_FILE,
                    reset_validations=True,
                )
                report.add_validation_result(
                    status=choices.VALIDATION_RESULT_CRITICAL,
                    message=response["blocking_error"],
                    data=str(response),
                    subject=choices.VAL_CAT_PACKAGE_FILE,
                )
                # falhou, retorna response
                package.finish_validations()
                return response

            if package.article:
                package.article.update_status()
            return response
    except GetXMLItemsError as exc:
        # identifica os erros do arquivo Zip / XML
        # TODO levar este código para o packtools / XMLWithPre
        return _identify_file_error(package)


def _identify_file_error(package):
    # identifica os erros do arquivo Zip / XML
    # TODO levar este código para o packtools / XMLWithPre
    try:
        xml_path = None
        xml_str = file_utils.get_xml_content_from_zip(package.file.path, xml_path)
        xml_utils.get_etree_from_xml_content(xml_str)
        return {}
    except (
        file_utils.BadPackageFileError,
        file_utils.PackageWithoutXMLFileError,
    ) as exc:
        message = exc.message
        data = None

    except xml_utils.XMLFormatError as e:
        data = {
            "column": e.column,
            "row": e.start_row,
            "snippet": xml_utils.get_snippet(xml_str, e.start_row, e.end_row),
        }
        message = e.message

    report = ValidationReport.create_or_update(
        package.creator,
        package,
        _("File Report"),
        choices.VAL_CAT_PACKAGE_FILE,
        reset_validations=True,
    )
    validation_result = report.add_validation_result(
        status=choices.VALIDATION_RESULT_FAILURE,
        message=message,
        data=data,
    )
    return {"blocking_error": message}


def _check_article_and_journal(xml_with_pre, user):
    # verifica se o XML está registrado no sistema
    response = {}
    try:
        response = pp.is_registered_xml_with_pre(xml_with_pre, xml_with_pre.filename)
        logging.info(f"is_registered_xml_with_pre: {response}")
        # verifica se o XML é esperado (novo, requer correção, requer atualização)
        _check_package_is_expected(response, xml_with_pre.sps_pkg_name)
        logging.info(f"_check_package_is_expected: {response}")

        # verifica se journal e issue estão registrados
        xmltree = xml_with_pre.xmltree

        _check_journal(response, xmltree, user)
        logging.info(f"_check_journal: {response}")
        _check_issue(response, xmltree, user)
        logging.info(f"_check_issue: {response}")

        # verifica a consistência dos dados de journal e issue
        # no XML e na base de dados
        _check_xml_and_registered_data_compability(response)
        logging.info(f"_check_xml_and_registered_data_compability: {response}")

        response["package_status"] = choices.PS_ENQUEUED_FOR_VALIDATION
        return response
    except UnexpectedPackageError as e:
        response["package_status"] = choices.PS_UNEXPECTED
        response["blocking_error"] = str(e)
        return response
    except PackageDataError as e:
        response["package_status"] = choices.PS_PENDING_CORRECTION
        response["blocking_error"] = str(e)
        return response


def _check_package_is_expected(response, sps_pkg_name):

    try:
        article = Article.objects.get(pid_v3=response["v3"])
    except (Article.DoesNotExist, KeyError):
        # artigo novo, inédito no sistema
        # buscar se o último pacote está pendente de correção, então é aceitável
        previous_package = (
            Package.objects.filter(name=sps_pkg_name).order_by("-created").first()
        )
        if not previous_package or previous_package.status == choices.PS_PENDING_CORRECTION:
            response["article"] = None
            response["package_category"] = choices.PC_NEW_DOCUMENT
            return
        raise UnexpectedPackageError(
            f"{sps_pkg_name} status={previous_package.status}. Unexpected updates."
        )
    else:
        previous_package = (
            Package.objects.filter(article=article).order_by("-created").first()
        )
        if previous_package:
            if previous_package.status == choices.PS_PENDING_CORRECTION:
                response["previous_package"] = previous_package.expiration_date
                if previous_package.expiration_date < datetime.utcnow():
                    raise UnexpectedPackageError(
                        f"The package is late. It was expected until {previous_package.expiration_date}"
                    )
            elif previous_package.status not in (
                choices.PS_REQUIRED_ERRATUM,
                choices.PS_REQUIRED_UPDATE,
            ):
                raise UnexpectedPackageError(
                    f"There is a previous package in progress ({previous_package.status}) for {article}"
                )

        response["article"] = article
        if article.status == article_choices.AS_REQUIRE_UPDATE:
            response["package_category"] = choices.PC_UPDATE
            article.status = article_choices.AS_UPDATE_SUBMITTED
            article.save()
        elif article.status == article_choices.AS_REQUIRE_ERRATUM:
            response["package_category"] = choices.PC_ERRATUM
            article.status = article_choices.AS_ERRATUM_SUBMITTED
            article.save()
        else:
            response["package_category"] = choices.PC_UPDATE
            raise UnexpectedPackageError(
                f"Package is rejected because the article status is: {article.status}"
            )


def _check_journal(response, xmltree, user):
    xml = Title(xmltree)
    journal_title = xml.journal_title

    xml = ISSN(xmltree)
    issn_electronic = xml.epub
    issn_print = xml.ppub

    response["journal"] = create_or_update_journal(
        journal_title, issn_electronic, issn_print, user
    )
    if not response["journal"]:
        raise PackageDataError(
            f"Not registered journal: {journal_title} {issn_electronic} {issn_print}"
        )


def _check_issue(response, xmltree, user):
    xml = ArticleMetaIssue(xmltree)
    response["issue"] = create_or_update_issue(
        response["journal"], xml.volume, xml.suppl, xml.number, user
    )
    if not response["issue"]:
        raise PackageDataError(
            f"Not registered issue: {response['journal']} {xml.volume} {xml.number} {xml.suppl}"
        )


def _check_xml_and_registered_data_compability(response):
    article = response["article"]

    if article:
        journal = response["journal"]
        if journal is not article.journal:
            raise PackageDataError(
                f"{article.journal} (registered) differs from {journal} (XML)"
            )

        issue = response["issue"]
        if issue is not article.issue:
            raise PackageDataError(
                f"{article.issue} (registered) differs from {issue} (XML)"
            )


def validate_xml_content(package, journal):
    params = {
        # "get_doi_data": callable_get_doi_data,
        "doi_required": journal.doi_prefix,
        "expected_toc_sections": journal.toc_sections,
        "journal_acron": journal.acron,
        "publisher_name_list": journal.publisher_names,
        "nlm_ta": journal.nlm_title,
        "journal_license_code": journal.license_code,
    }
    try:
        for xml_with_pre in XMLWithPre.create(path=package.file.path):
            _validate_xml_content(xml_with_pre, package, params)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "operation": "upload.controller.validate_xml_content",
                "detail": dict(file_path=package.file.path),
            },
        )


def _validate_xml_content(xml_with_pre, package, params):

    try:
        info_report = XMLInfoReport.create_or_update(
            package.creator,
            package,
            _("XML Info Report"),
            choices.VAL_CAT_XML_CONTENT,
            reset_validations=True,
        )
        XMLError.objects.filter(report__package=package).delete()
        error_report = XMLErrorReport.create_or_update(
            package.creator,
            package,
            _("XML Error Report"),
            choices.VAL_CAT_XML_CONTENT,
            reset_validations=True,
        )

        results = xml_validation.validate_xml_content(
            xml_with_pre.sps_pkg_name, xml_with_pre.xmltree, params
        )
        for result in results:
            if result.get("exception"):
                _handle_exception(**result)
            else:
                _handle_xml_content_validation_result(
                    package,
                    xml_with_pre.sps_pkg_name,
                    result,
                    info_report,
                    error_report,
                )
        info_report.finish_validations()
        for error_report in package.xml_error_report.all():
            if error_report.xml_error.count():
                error_report.finish_validations()
            else:
                error_report.delete()
        # devido às tarefas serem executadas concorrentemente,
        # necessário verificar se todas tarefas finalizaram e
        # então finalizar o pacote
        package.finish_validations()

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "operation": "upload.controller._validate_xml_content",
                "detail": {
                    "file": package.file.path,
                    "item": xml_with_pre.sps_pkg_name,
                    "exception": str(e),
                    "exception_type": str(type(e)),
                },
            },
        )


def _handle_xml_content_validation_result(
    package, sps_pkg_name, result, info_report, error_report
):
    # ['xpath', 'advice', 'title', 'expected_value', 'got_value', 'message', 'validation_type', 'response']

    try:
        status_ = result["response"]
        if status_ == "OK":
            report = info_report
        else:

            group = result.get("group") or result.get("item")
            if not group and result.get("exception_type"):
                group = "configuration"
            if group:
                report = XMLErrorReport.create_or_update(
                    package.creator,
                    package,
                    _("XML Error Report") + f": {group}",
                    group,
                    reset_validations=False,
                )
            else:
                report = error_report

        message = result.get("message") or ""
        advice = result.get("advice") or ""
        message = ". ".join([_(message), _(advice)])

        validation_result = report.add_validation_result(
            status=status_,
            message=result.get("message"),
            data=result,
            subject=result.get("item"),
        )
        validation_result.focus = result.get("title")
        validation_result.attribute = result.get("sub_item")
        validation_result.parent = result.get("parent")
        validation_result.parent_id = result.get("parent_id")
        validation_result.parent_article_type = result.get("parent_article_type")
        validation_result.validation_type = result.get("validation_type") or "xml"

        if status_ != "OK":
            validation_result.advice = result.get("advice")
            validation_result.expected_value = result.get("expected_value")
            validation_result.got_value = result.get("got_value")
            validation_result.reaction = choices.ER_REACTION_FIX

        try:
            validation_result.save()
        except Exception as e:
            print(result)
            logging.exception(e)
            for k, v in result.items():
                print((k, len(str(v)), v))

        return validation_result
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "operation": "upload.controller._handle_xml_content_validation_result",
                "detail": {
                    "file": package.file.path,
                    "item": sps_pkg_name,
                    "result": result,
                    "exception": str(e),
                    "exception_type": str(type(e)),
                },
            },
        )


def _handle_exception(exception, exc_traceback, function, sps_pkg_name, item=None):
    detail = {
        "function": function,
        "sps_pkg_name": sps_pkg_name,
        "item": item and str(item),
    }
    UnexpectedEvent.create(
        exception=exception,
        exc_traceback=exc_traceback,
        detail=detail,
    )
