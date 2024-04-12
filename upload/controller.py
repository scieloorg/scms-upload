import logging
import sys
from datetime import datetime
from zipfile import ZipFile, ZIP_DEFLATED

from django.utils.translation import gettext as _
from packtools.sps.models.journal_meta import Title, ISSN
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre, GetXMLItemsError
from packtools.sps.models.front_articlemeta_issue import ArticleMetaIssue

from article.controller import create_article
from article import choices as article_choices
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
from .utils import file_utils, package_utils, xml_utils

from upload import xml_validation
from pid_provider.requester import PidRequester
from article.models import Article
from core.utils.requester import fetch_data
from issue.models import Issue
from journal.models import OfficialJournal, Journal
from tracker.models import UnexpectedEvent, serialize_detail
from upload.xml_validation import (
    validate_xml_content,
    add_app_data,
    add_sps_data,
    add_journal_data,
)

pp = PidRequester()


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


def receive_package(request, package):
    try:
        zip_xml_file_path = package.file.path
        for xml_with_pre in XMLWithPre.create(path=zip_xml_file_path):
            response = _check_article_and_journal(request, xml_with_pre)
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
                package._add_validation_result(
                    error_category=error_category,
                    status=choices.VS_DISAPPROVED,
                    message=response["error"],
                    data=serialize_detail(response),
                )
                # falhou, retorna response
                return response
        # sucesso, retorna package
        package._add_validation_result(
            error_category=choices.VE_XML_FORMAT_ERROR,
            status=choices.VS_APPROVED,
            message=None,
            data={
                "xml_path": package.file.path,
            },
        )
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
        package._add_validation_result(
            error_category=choices.VE_PACKAGE_FILE_ERROR,
            message=exc.message,
            status=choices.VS_DISAPPROVED,
            data={"exception": str(exc), "exception_type": str(type(exc))},
        )
        return {"error": str(exc), "error_type": choices.VE_PACKAGE_FILE_ERROR}

    except xml_utils.XMLFormatError as e:
        data = {
            "xml_path": package.file.path,
            "column": e.column,
            "row": e.start_row,
            "snippet": xml_utils.get_snippet(xml_str, e.start_row, e.end_row),
        }
        package._add_validation_result(
            error_category=choices.VE_XML_FORMAT_ERROR,
            message=e.message,
            data=data,
            status=choices.VS_DISAPPROVED,
        )
        return {"error": str(e), "error_type": choices.VE_XML_FORMAT_ERROR}


def _check_article_and_journal(request, xml_with_pre):
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

    #Verifica e atribui journal e issue pela api
    _verify_journal_and_issue_in_upload(request, xmltree)

    # verifica se journal e issue estão registrados
    _check_xml_journal_and_xml_issue_are_registered(request, 
        xml_with_pre.filename, xmltree, response
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


def _verify_journal_and_issue_in_upload(request, xmltree):
    journal = fetch_core_api_and_create_or_update_journal(request, xmltree)
    fetch_core_api_and_create_or_update_issue(request, xmltree, journal)


def fetch_core_api_and_create_or_update_journal(request, xmltree):
    user = request.user
    xml = Title(xmltree)
    journal_title = xml.journal_title

    xml = ISSN(xmltree)
    issn_electronic = xml.epub
    issn_print = xml.ppub

    response = fetch_data(
        url=f"http://0.0.0.0:8009/api/v1/journal/", 
        params={
            "title": journal_title,
            "issn_print": issn_print, 
            "issn_electronic": issn_electronic},
        json=True
    )
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


def fetch_core_api_and_create_or_update_issue(request, xmltree, journal):
    user = request.user
    xml = ArticleMetaIssue(xmltree)
    if journal and any((xml.volume, xml.suppl, xml.number)):
        issn_print = journal.official_journal.issn_print
        issn_electronic = journal.official_journal.issn_electronic
        response = fetch_data(
            url=f"http://0.0.0.0:8009/api/v1/issue/", 
            params={
                "issn_print": issn_print,
                "issn_electronic": issn_electronic, 
                "number": xml.number, 
                # "season": xml.suppl,
                "volume": xml.volume
                },
            json=True
        )

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
                supplement=None,
                number=issue.get("number"),
                publication_year=issue.get("year"),
                user=user
            )
            return issue 


def _check_xml_journal_and_xml_issue_are_registered(request, filename, xmltree, response):
    """
    Verifica se journal e issue do XML estão registrados no sistema
    """
    resp = {}
    resp = _check_journal(filename, xmltree)
    response.update(resp)
    resp = _check_issue(filename, xmltree, resp["journal"])
    response.update(resp)


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


def _check_journal(origin, xmltree):
    try:
        xml = Title(xmltree)
        journal_title = xml.journal_title

        xml = ISSN(xmltree)
        issn_electronic = xml.epub
        issn_print = xml.ppub
        return dict(journal=_get_journal(journal_title, issn_electronic, issn_print))
    except Journal.DoesNotExist as exc:
        logging.exception(exc)
        return dict(
            error=f"Journal in XML is not registered in Upload: {journal_title} (electronic: {issn_electronic}, print: {issn_print})",
            error_type=choices.VE_ARTICLE_JOURNAL_INCOMPATIBILITY_ERROR,
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


def _check_issue(origin, xmltree, journal):
    try:
        xml = ArticleMetaIssue(xmltree)
        if any((xml.volume, xml.suppl, xml.number)):
            return {"issue": Issue.get(journal, xml.volume, xml.suppl, xml.number)}
        else:
            return {"issue": None}
    except Issue.DoesNotExist:
        return dict(
            error=f"Issue in XML is not registered in Upload: {journal} {xml.data}",
            error_type=choices.VE_DATA_CONSISTENCY_ERROR,
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
    # VE_BIBLIOMETRICS_DATA_ERROR = "bibliometrics-data-error"
    # VE_SERVICES_DATA_ERROR = "services-data-error"
    # VE_DATA_CONSISTENCY_ERROR = "data-consistency-error"
    # VE_CRITERIA_ISSUES_ERROR = "criteria-issues-error"

    # TODO completar data
    data = {}
    # add_app_data(data, app_data)
    # add_journal_data(data, journal, issue)
    # add_sps_data(data, sps_data)

    try:
        for xml_with_pre in XMLWithPre.create(path=package.file.path):
            _validate_xml_content(package, xml_with_pre, data)
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


def _validate_xml_content(package, xml_with_pre, data):
    # TODO completar data
    data = {}
    # xml_validation.add_app_data(data, app_data)
    # xml_validation.add_journal_data(data, journal, issue)
    # xml_validation.add_sps_data(data, sps_data)

    try:
        results = xml_validation.validate_xml_content(
            xml_with_pre.sps_pkg_name, xml_with_pre.xmltree, data
        )
        for result in results:
            _handle_xml_content_validation_result(
                package, xml_with_pre.sps_pkg_name, result
            )
        try:
            error = ValidationResult.objects.filter(
                package=package,
                status=choices.VS_DISAPPROVED,
                category__in=choices.VALIDATION_REPORT_ITEMS[
                    choices.VR_INDIVIDUAL_CONTENT
                ],
            )[0]
            package.status = choices.PS_VALIDATED_WITH_ERRORS
        except IndexError:
            # nenhum erro
            package.status = choices.PS_VALIDATED_WITHOUT_ERRORS
        package.save()
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


def _handle_xml_content_validation_result(package, sps_pkg_name, result):
    # ['xpath', 'advice', 'title', 'expected_value', 'got_value', 'message', 'validation_type', 'response']

    try:
        if result["response"] == "OK":
            status = choices.VS_APPROVED
        else:
            status = choices.VS_DISAPPROVED

        # VE_BIBLIOMETRICS_DATA_ERROR, VE_SERVICES_DATA_ERROR,
        # VE_DATA_CONSISTENCY_ERROR, VE_CRITERIA_ISSUES_ERROR,
        error_category = result.get("error_category") or choices.VE_XML_CONTENT_ERROR

        message = result["message"]
        advice = result["advice"] or ""
        message = ". ".join([_(message), _(advice)])
        package._add_validation_result(
            error_category=error_category,
            status=status,
            message=message,
            data=result,
        )
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
