import logging
import sys
from datetime import datetime
from zipfile import ZIP_DEFLATED, ZipFile

from django.utils.translation import gettext as _
from packtools.sps.models.front_articlemeta_issue import ArticleMetaIssue
from packtools.sps.models.journal_meta import ISSN, Title
from packtools.sps.pid_provider.xml_sps_lib import GetXMLItemsError, XMLWithPre

from article import choices as article_choices
from article.controller import create_article
from article.models import Article
from collection.models import WebSiteConfiguration
from core.utils.requester import fetch_data
from issue.models import Issue
from journal.models import Journal, OfficialJournal
from libs.dsm.publication.db import exceptions, mk_connection
from package import choices as package_choices
from package.models import SPSPkg
from pid_provider.requester import PidRequester
from tracker.models import UnexpectedEvent, serialize_detail
from upload import xml_validation
from upload.models import ValidationReport, XMLErrorReport, XMLInfoReport
from upload.xml_validation import validate_xml_content

from .models import (
    Package,
    choices,
)
from .utils import file_utils, package_utils, xml_utils

pp = PidRequester()


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
            package.issue = response.get("issue")
            package.journal = response.get("journal")
            package.category = response.get("package_category")
            package.status = response.get("package_status")
            package.save()

            error_category = response.get("error_type")
            if error_category:
                report = ValidationReport.get_or_create(
                    user=user,
                    package=package,
                    title=_("Package file"),
                    category=choices.VAL_CAT_PACKAGE_FILE,
                )
                report.add_validation_result(
                    status=choices.VALIDATION_RESULT_FAILURE,
                    message=response["error"],
                    data=serialize_detail(response),
                    subject=choices.VAL_CAT_PACKAGE_FILE,
                )
                # falhou, retorna response
                return response
        return response
    except GetXMLItemsError as exc:
        # identifica os erros do arquivo Zip / XML
        return _identify_file_error(package)


def _identify_file_error(package):
    # identifica os erros do arquivo Zip / XML
    try:
        xml_path = None
        xml_str = file_utils.get_xml_content_from_zip(package.file.path, xml_path)
        xml_utils.get_etree_from_xml_content(xml_str)
        return {}
    except (
        file_utils.BadPackageFileError,
        file_utils.PackageWithoutXMLFileError,
    ) as exc:
        result = dict(
            error_category=choices.VE_PACKAGE_FILE_ERROR,
            message=exc.message,
            status=choices.VS_DISAPPROVED,
            data={"exception": str(exc), "exception_type": str(type(exc))},
        )
        error = {"error": str(exc), "error_type": choices.VE_PACKAGE_FILE_ERROR}

    except xml_utils.XMLFormatError as e:
        data = {
            "xml_path": package.file.path,
            "column": e.column,
            "row": e.start_row,
            "snippet": xml_utils.get_snippet(xml_str, e.start_row, e.end_row),
        }
        result = dict(
            error_category=choices.VE_XML_FORMAT_ERROR,
            message=e.message,
            data=data,
            status=choices.VS_DISAPPROVED,
        )
        error = {"error": str(e), "error_type": choices.VE_XML_FORMAT_ERROR}

    report = ValidationReport.get_or_create(
        package.creator, package, _("File Report"), choices.VAL_CAT_PACKAGE_FILE
    )
    validation_result = report.add_validation_result(
        status=choices.VALIDATION_RESULT_FAILURE,
        message=result["message"],
        data=result["data"],
    )
    return error


def _check_article_and_journal(xml_with_pre, user):
    # verifica se o XML está registrado no sistema
    response = pp.is_registered_xml_with_pre(xml_with_pre, xml_with_pre.filename)

    # verifica se o XML é esperado
    article_previous_status = _check_package_is_expected(response)

    # verifica se XML já está associado a um article
    try:
        article = response.pop("article")
    except KeyError:
        article = None

    # caso encontrado erro, sair da função
    if response.get("error"):
        return _handle_error(response, article, article_previous_status)

    xmltree = xml_with_pre.xmltree

    # verifica se journal e issue estão registrados
    _check_xml_journal_and_xml_issue_are_registered(
        xml_with_pre.filename, xmltree, response, user
    )

    # caso encontrado erro, sair da função
    if response.get("error"):
        return _handle_error(response, article, article_previous_status)

    if article:
        # verifica a consistência dos dados de journal e issue
        # no XML e na base de dados
        _compare_journal_and_issue_from_xml_to_journal_and_issue_from_article(
            article, response
        )
        if response.get("error"):
            # inconsistências encontradas
            return _handle_error(response, article, article_previous_status)
        else:
            # sem problemas
            response["package_status"] = choices.PS_ENQUEUED_FOR_VALIDATION
            response.update({"article": article})

            return response
    # documento novo
    response["package_status"] = choices.PS_ENQUEUED_FOR_VALIDATION

    return response


def _handle_error(response, article, article_previous_status):
    _rollback_article_status(article, article_previous_status)
    response["package_status"] = choices.PS_REJECTED
    return response


def _check_package_is_expected(response):
    article = None
    try:
        response["article"] = Article.objects.get(pid_v3=response["v3"])
        return _get_article_previous_status(response["article"], response)
    except (Article.DoesNotExist, KeyError):
        # TODO verificar journal, issue
        response["package_category"] = choices.PC_NEW_DOCUMENT


def _get_article_previous_status(article, response):
    article_previos_status = article.status
    if article.status == article_choices.AS_REQUIRE_UPDATE:
        article.status = article_choices.AS_CHANGE_SUBMITTED
        article.save()
        response["package_category"] = choices.PC_UPDATE
        return article_previos_status
    elif article.status == article_choices.AS_REQUIRE_ERRATUM:
        article.status = article_choices.AS_CHANGE_SUBMITTED
        article.save()
        response["package_category"] = choices.PC_ERRATUM
        return article_previos_status
    else:
        response[
            "error"
        ] = f"Unexpected package. Article has no need to be updated / corrected. Article status: {article_previos_status}"
        response["error_type"] = choices.VE_FORBIDDEN_UPDATE_ERROR
        response["package_category"] = choices.PC_UPDATE


def _rollback_article_status(article, article_previos_status):
    if article_previos_status:
        # rollback
        article.status = article_previos_status
        article.save()


# def _verify_journal_and_issue_in_upload(xmltree, user):
#     journal = fetch_core_api_and_create_or_update_journal(xmltree, user)
#     fetch_core_api_and_create_or_update_issue(user, xmltree, journal)


def fetch_core_api_and_create_or_update_journal(
    journal_title, issn_electronic, issn_print, user
):
    try:
        response = fetch_data(
            url=f"https://core.scielo.org/api/v1/journal/",
            params={
                "title": journal_title,
                "issn_print": issn_print,
                "issn_electronic": issn_electronic,
            },
            json=True,
        )
    except Exception as e:
        logging.exception(e)
        return

    for journal in response.get("results"):
        official_journal = OfficialJournal.create_or_update(
            title=journal.get("official").get("title"),
            title_iso=journal.get("official").get("iso_short_title"),
            issn_print=journal.get("official").get("issn_print"),
            issn_electronic=journal.get("official").get("issn_electronic"),
            issnl=journal.get("official").get("issnl"),
            foundation_year=None,
            user=user,
        )
        journal = Journal.create_or_update(
            official_journal=official_journal,
            title=journal.get("title"),
            short_title=journal.get("short_title"),
            user=user,
        )
        return journal


def fetch_core_api_and_create_or_update_issue(user, xml, journal):
    if journal and any((xml.volume, xml.suppl, xml.number)):
        issn_print = journal.official_journal.issn_print
        issn_electronic = journal.official_journal.issn_electronic
        try:
            response = fetch_data(
                url=f"https://core.scielo.org/api/v1/issue/",
                params={
                    "issn_print": issn_print,
                    "issn_electronic": issn_electronic,
                    "number": xml.number,
                    "supplement": xml.suppl,
                    "volume": xml.volume,
                },
                json=True,
            )

        except Exception as e:
            logging.exception(e)
            return

        for issue in response.get("results"):
            official_journal = OfficialJournal.get(
                issn_electronic=issue.get("journal").get("issn_electronic"),
                issn_print=issue.get("journal").get("issn_print"),
                issnl=issue.get("journal").get("issn_issnl"),
            )
            journal = Journal.get(official_journal=official_journal)
            issue = Issue.get_or_create(
                journal=journal,
                volume=issue.get("volume"),
                supplement=issue.get("supplement"),
                number=issue.get("number"),
                publication_year=issue.get("year"),
                user=user,
            )
            return issue


def _check_xml_journal_and_xml_issue_are_registered(filename, xmltree, response, user):
    """
    Verifica se journal e issue do XML estão registrados no sistema
    """
    resp = {}
    resp = _check_journal(filename, xmltree, user)
    response.update(resp)
    try:
        resp = _check_issue(filename, xmltree, resp["journal"], user)
        response.update(resp)
    except KeyError:
        pass


def _get_journal(journal_title, issn_electronic, issn_print):
    j = None
    if issn_electronic:
        try:
            j = OfficialJournal.objects.get(issn_electronic=issn_electronic)
        except OfficialJournal.DoesNotExist:
            pass

    if not j and issn_print:
        try:
            j = OfficialJournal.objects.get(issn_print=issn_print)
        except OfficialJournal.DoesNotExist:
            pass

    if not j and journal_title:
        try:
            j = OfficialJournal.objects.get(title=journal_title)
        except OfficialJournal.DoesNotExist:
            pass

    if j:
        return Journal.objects.get(official_journal=j)
    raise Journal.DoesNotExist(f"{journal_title} {issn_electronic} {issn_print}")


def _check_journal(origin, xmltree, user):
    try:
        xml = Title(xmltree)
        journal_title = xml.journal_title

        xml = ISSN(xmltree)
        issn_electronic = xml.epub
        issn_print = xml.ppub

        try:
            return dict(
                journal=_get_journal(journal_title, issn_electronic, issn_print)
            )
        except Journal.DoesNotExist as exc:
            return dict(
                journal=fetch_core_api_and_create_or_update_journal(
                    journal_title, issn_electronic, issn_print, user
                )
            )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "operation": "upload.controller._check_journal",
                "detail": dict(origin=origin),
            },
        )
        return {"error": str(e), "error_type": choices.VE_UNEXPECTED_ERROR}


def _check_issue(origin, xmltree, journal, user):
    try:
        try:
            xml = ArticleMetaIssue(xmltree)
            if any((xml.volume, xml.suppl, xml.number)):
                return {"issue": Issue.get(journal, xml.volume, xml.suppl, xml.number)}
            else:
                return {"issue": None}
        except Issue.DoesNotExist:
            return dict(
                issue=fetch_core_api_and_create_or_update_issue(user, xml, journal)
            )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "operation": "upload.controller._check_issue",
                "detail": dict(origin=origin),
            },
        )
        return {"error": str(e), "error_type": choices.VE_UNEXPECTED_ERROR}


def _compare_journal_and_issue_from_xml_to_journal_and_issue_from_article(
    article, response
):
    issue = response["issue"]
    journal = response["journal"]
    if article.issue is issue and article.journal is journal:
        response["package_status"] = choices.PS_ENQUEUED_FOR_VALIDATION
    elif article.issue is issue:
        response.update(
            dict(
                error=f"{article.journal} (registered) differs from {journal} (XML)",
                error_type=choices.VE_ARTICLE_JOURNAL_INCOMPATIBILITY_ERROR,
            )
        )
    else:
        response.update(
            dict(
                error=f"{article.journal} {article.issue} (registered) differs from {journal} {issue} (XML)",
                error_type=choices.VE_DATA_CONSISTENCY_ERROR,
            )
        )


def validate_xml_content(package, journal, issue):
    try:
        for xml_with_pre in XMLWithPre.create(path=package.file.path):
            _validate_xml_content(xml_with_pre, package, journal, issue)
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


def _validate_xml_content(xml_with_pre, package, journal, issue):

    try:
        info_report = XMLInfoReport.get_or_create(
            package.creator, package, _("XML Info Report"), choices.VAL_CAT_XML_CONTENT
        )
        error_report = XMLErrorReport.get_or_create(
            package.creator, package, _("XML Error Report"), choices.VAL_CAT_XML_CONTENT
        )

        results = xml_validation.validate_xml_content(
            xml_with_pre.sps_pkg_name, xml_with_pre.xmltree, journal, issue
        )
        for result in results:
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
                report = XMLErrorReport.get_or_create(
                    package.creator,
                    package,
                    _("XML Error Report") + f": {group}",
                    group,
                )
            else:
                report = error_report

        # VE_BIBLIOMETRICS_DATA_ERROR, VE_SERVICES_DATA_ERROR,
        # VE_DATA_CONSISTENCY_ERROR, VE_CRITERIA_ISSUES_ERROR,
        error_category = result.get("error_category") or choices.VE_XML_CONTENT_ERROR

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

        if status_ == choices.VALIDATION_RESULT_FAILURE:
            validation_result.advice = result.get("advice")
            validation_result.expected_value = result.get("expected_value")
            validation_result.got_value = result.get("got_value")
            validation_result.reaction = choices.ER_REACTION_FIX

        validation_result.save()
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
