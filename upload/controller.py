import os
import logging
import sys
import traceback
from datetime import datetime
from zipfile import ZIP_DEFLATED, ZipFile
from tempfile import TemporaryDirectory

from django.db.models import Q
from django.utils.translation import gettext as _
from packtools.sps.models.article_dates import ArticleDates
from packtools.sps.models.front_articlemeta_issue import ArticleMetaIssue
from packtools.sps.models.journal_meta import ISSN, Title
from packtools.sps.pid_provider.xml_sps_lib import GetXMLItemsError, XMLWithPre

from article import choices as article_choices
from article.models import Article
from collection.models import WebSiteConfiguration
from issue.models import Issue
from journal.models import Journal, OfficialJournal
from package import choices as package_choices
from package.models import SPSPkg, update_zip_file
from pid_provider.requester import PidRequester
from proc.controller import create_or_update_journal, create_or_update_issue
from tracker.models import UnexpectedEvent
from upload.validation import xml_validation
from upload.models import (
    Package,
    PackageZip,
    ValidationReport,
    XMLError,
    XMLErrorReport,
    XMLInfoReport,
    choices,
)
from upload.utils import file_utils, package_utils, xml_utils

pp = PidRequester()


class UnexpectedPackageError(Exception): ...


class PackageDataError(Exception): ...


def get_last_package(article_id, **kwargs):
    try:
        return (
            Package.objects.filter(article=article_id, **kwargs)
            .order_by("-created")
            .first()
        )
    except Package.DoesNotExist:
        return


def receive_package(user, package):
    try:
        zip_xml_file_path = package.file.path
        response = {}
        for xml_with_pre in XMLWithPre.create(path=zip_xml_file_path):

            # atualiza package name e linked
            # TODO melhorar a forma de fazer link entre os artigos do pacote
            if xml_with_pre.xmltree.find(".//related-article"):
                for item in package.pkg_zip.packages.all():
                    if item is not package:
                        package.linked.add(item)
            package.main_doi = xml_with_pre.main_doi
            package.add_order(xml_with_pre.order, xml_with_pre.fpage)
            package.save()

            response = _check_article_and_journal(package, xml_with_pre, user=user)
            logging.info(response)
            update_zip_file(zip_xml_file_path, response, xml_with_pre)

            package.article = response.get("article")
            package.issue = (
                response.get("issue") or package.article and package.article.issue
            )
            package.journal = (
                response.get("journal") or package.article and package.article.journal
            )
            package.category = response.get("package_category")
            package.status = response.get("package_status")
            package.expiration_date = response.get("expiration_date")
            package.save()

            error = (
                response.get("error_message")
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
                    status=response["error_level"],
                    message=response["error_message"],
                    data=str(response),
                    subject=choices.VAL_CAT_PACKAGE_FILE,
                )
                # falhou, retorna response
                report.finish_validations()
                package.finish_validations(blocking_error_status=response.get("package_status"))
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
    return {"error_message": message, "error_level": choices.VALIDATION_RESULT_BLOCKING}


def _check_article_and_journal(package, xml_with_pre, user):
    # verifica se o XML está registrado no sistema
    response = {}
    try:
        response = pp.is_registered_xml_with_pre(xml_with_pre, xml_with_pre.filename)
        logging.info(f"is_registered_xml_with_pre: {response}")
        # verifica se o XML é esperado (novo, requer correção, requer atualização)
        name, ext = os.path.splitext(xml_with_pre.filename)
        _check_package_is_expected(response, package, name)
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

        _archive_pending_correction_package(response, name)
        return response
    except UnexpectedPackageError as e:
        response["package_status"] = choices.PS_UNEXPECTED
        response["error_message"] = str(e)
        response["error_level"] = choices.VALIDATION_RESULT_BLOCKING
        return response
    except PackageDataError as e:
        response["package_status"] = choices.PS_PENDING_CORRECTION
        response["error_message"] = str(e)
        response["error_level"] = choices.VALIDATION_RESULT_BLOCKING
        return response
    except Exception as e:
        response["package_status"] = choices.PS_PENDING_CORRECTION
        response["error_message"] = str(e)
        response["error_level"] = choices.VALIDATION_RESULT_BLOCKING
        return response


def _check_package_is_expected(response, package, sps_pkg_name):
    try:
        article = Article.objects.get(pid_v3=response["v3"])
        params = {"article": article}
    except (Article.DoesNotExist, KeyError):
        # artigo novo, inédito no sistema
        article = None
        params = {"name": sps_pkg_name}

    logging.info(f"_check_package_is_expected: {params}")
    try:
        # se o pacote anterior está pendente de correção, então é aceitável
        previous_package = Package.objects.filter(**params).order_by("-created")[1]
    except IndexError:
        previous_package = None

    response["article"] = article

    if previous_package and previous_package.status in choices.PS_WIP:
        raise UnexpectedPackageError(
            _("Not allowed to accept new package. There is a previous package which status={}. Search it and change the status to '{}'").format(
                previous_package.status, choices.PS_PENDING_CORRECTION
            )
        )

    if article:
        if article.status == article_choices.AS_REQUIRE_UPDATE:
            response["package_category"] = choices.PC_UPDATE
        elif article.status == article_choices.AS_REQUIRE_ERRATUM:
            response["package_category"] = choices.PC_ERRATUM
        else:
            response["package_category"] = choices.PC_UPDATE

            raise UnexpectedPackageError(
                _("Not allowed to accept new package. There is a previous package which status={}. Search it and change the status to '{}'").format(
                    article.status, choices.PS_PENDING_CORRECTION
                )
            )
    else:
        response["package_category"] = choices.PC_NEW_DOCUMENT
        return


def _archive_pending_correction_package(response, name):
    params = {}
    if response.get("article"):
        params["article"] = response.get("article")
    else:
        params["name"] = name
    Package.objects.filter(
        **params, status=choices.PS_PENDING_CORRECTION
    ).update(status=choices.PS_ARCHIVED)


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
        data = {
            "journal_title": journal_title,
            "issn_electronic": issn_electronic,
            "issn_print": issn_print,
        }
        similar_journals = []
        for j in Journal.get_similar_items(journal_title, issn_electronic, issn_print):
            similar_journals.append(
                {
                    "journal_title": j.title,
                    "issn_electronic": j.official_journal.issn_electronic,
                    "issn_print": j.official_journal.issn_print,
                }
            )
        if similar_journals:
            similar_journals = _("Expected journal data: {}. ").format(similar_journals)
        else:
            similar_journals = _(
                "No journal with similar data is registered in the system"
            )
        raise PackageDataError(
            _(
                "Journal data in XML: {}. {}Check and fix the journal data in XML"
            ).format(data, similar_journals)
        )


def _check_issue(response, xmltree, user):
    xml = ArticleDates(xmltree)
    try:
        publication_year = xml.collection_date["year"]
    except (TypeError, KeyError, ValueError):
        try:
            publication_year = xml.article_date["year"]
        except (TypeError, KeyError, ValueError):
            publication_year = None

    xml = ArticleMetaIssue(xmltree)
    response["issue"] = create_or_update_issue(
        response["journal"], publication_year, xml.volume, xml.suppl, xml.number, user
    )
    logging.info(f"issue: {response['issue']}")
    if not response["issue"]:
        data = {
            "journal": response["journal"],
            "volume": xml.volume,
            "number": xml.number,
            "suppl": xml.suppl,
            "publication_year": publication_year,
        }
        logging.info(f"_check_issue {data}")
        items = None
        if publication_year and xml.volume:
            items = Issue.objects.filter(
                Q(publication_year=publication_year) | Q(volume=xml.volume),
                journal=response["journal"],
            )
        elif publication_year:
            items = Issue.objects.filter(
                Q(publication_year=publication_year), journal=response["journal"]
            )
        if not items or not items.count():
            items = Issue.objects.filter(journal=response["journal"])

        issues = []
        for item in items.order_by("-publication_year"):
            issues.append(
                {
                    "publication_year": publication_year,
                    "volume": item.volume,
                    "number": item.number,
                    "supplement": item.supplement,
                }
            )
        if issues:
            issues = _("Expected issue data: {}. ").format(issues)
        else:
            issues = _("No issue with similar data is registered in the system")
        raise PackageDataError(
            _("Issue data in XML: {}. {}Check and fix the issue data in XML").format(
                data, issues
            )
        )


def _check_xml_and_registered_data_compability(response):
    article = response["article"]

    if article:
        journal = response["journal"]
        if not journal == article.journal:
            raise PackageDataError(
                _("{} (registered, {}) differs from {} (XML, {})").format(
                    article.journal, article.journal.id, journal, journal.id
                )
            )

        issue = response["issue"]
        if not issue == article.issue:
            raise PackageDataError(
                _("{} (registered, {}) differs from {} (XML, {})").format(
                    article.issue, article.issue.id, issue, issue.id
                )
            )


def validate_xml_content(package, journal):
    params = {
        # "get_doi_data": callable_get_doi_data,
        "doi_required": journal.doi_prefix,
        "expected_toc_sections": journal.toc_sections,
        "journal_acron": journal.journal_acron,
        "publisher_name_list": journal.publisher_names,
        "nlm_ta": journal.nlm_title,
        "journal_license_code": journal.license_code,
    }
    try:
        for xml_with_pre in XMLWithPre.create(path=package.file.path):
            return _validate_xml_content(xml_with_pre, package, params)
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
        return True

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
