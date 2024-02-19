import logging
import sys
from datetime import datetime

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
from pid_provider.requester import PidRequester
from article.models import Article
from issue.models import Issue
from journal.models import OfficialJournal, Journal
from tracker.models import UnexpectedEvent

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


def receive_package(package):
    try:
        for xml_with_pre in XMLWithPre.create(path=package.file.path):
            response = _check_article_and_journal(xml_with_pre)

            package.article = response.get("article")
            package.category = response.get("package_category")
            package.status = response.get("package_status")
            package.save()

            error_category = response.get("error_type")
            if error_category:
                package._add_validation_result(
                    error_category=error_category,
                    status=choices.VS_DISAPPROVED,
                    message=response["error"],
                    data={},
                )
                # falhou, retorna response
                return package
        # sucesso, retorna package
        package._add_validation_result(
            error_category=choices.VE_XML_FORMAT_ERROR,
            status=choices.VS_APPROVED,
            message=None,
            data={
                "xml_path": package.file.path,
            },
        )
        return package
    except GetXMLItemsError as exc:
        # identifica os erros do arquivo Zip / XML
        _identify_file_error(package)
        return package


def _identify_file_error(package):
    # identifica os erros do arquivo Zip / XML
    try:
        xml_path = None
        xml_str = file_utils.get_xml_content_from_zip(package.file.path, xml_path)
        xml_utils.get_etree_from_xml_content(xml_str)
    except (file_utils.BadPackageFileError, file_utils.PackageWithoutXMLFileError) as e:
        package._add_validation_result(
            error_category=choices.VE_PACKAGE_FILE_ERROR,
            message=e.message,
            status=choices.VS_DISAPPROVED,
            data={"exception": str(exc), "exception_type": str(type(exc))},
        )

    except xml_utils.XMLFormatError as e:
        data = {
            "xml_path": package.file.path,
            "column": e.column,
            "row": e.start_row,
            "snippet": xml_utils.get_snippet(xml_str, e.start_row, e.end_row),
        }
        val.update(
            error_category=choices.VE_XML_FORMAT_ERROR,
            message=e.message,
            data=data,
            status=choices.VS_DISAPPROVED,
        )


def _check_article_and_journal(xml_with_pre):
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
        xml_with_pre.filename, xmltree, response
    )
    # caso encontrado erro, sair da função
    if response.get("error"):
        return _handle_error(response, article, article_previous_status)

    if article:
        # verifica a consistência dos dados de journal e issue
        # no XML e na base de dados
        _compare_journal_and_issue_from_xml_to_journal_and_issue_from_article(article, response)
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
        response["error"] = f"Unexpected package. Article has no need to be updated / corrected. Article status: {article_previos_status}"
        response["error_type"] = choices.VE_FORBIDDEN_UPDATE_ERROR
        response["package_category"] = choices.PC_UPDATE


def _rollback_article_status(article, article_previos_status):
    if article_previos_status:
        # rollback
        article.status = article_previos_status
        article.save()


def _check_xml_journal_and_xml_issue_are_registered(filename, xmltree, response):
    """
    Verifica se journal e issue do XML estão registrados no sistema
    """
    try:
        resp = {}
        resp = _check_journal(filename, xmltree)
        journal = resp["journal"]
        resp = _check_issue(filename, xmltree, journal)
        issue = resp["issue"]
        response.update({"journal": journal, "issue": issue})
    except KeyError:
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
            j = OfficialJournal.objects.get(journal_title=journal_title)
        except OfficialJournal.DoesNotExist:
            pass

    if j:
        return Journal.objects.get(official=j)
    raise Journal.DoesNotExist(f"{journal_title} {issn_electronic} {issn_print}")


def _check_journal(origin, xmltree):
    try:
        xml = Title(xmltree)
        journal_title = xml.journal_title

        xml = ISSN(xmltree)
        issn_electronic = xml.epub
        issn_print = xml.ppub

        return dict(journal=_get_journal(journal_title, issn_electronic, issn_print))
    except Journal.DoesNotExist:
        return dict(
            error=f"Journal in XML is not registered in Upload: {journal_title} {issn_electronic} (electronic) {issn_print} (print)",
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
        logging.info(xml.data)
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


def _compare_journal_and_issue_from_xml_to_journal_and_issue_from_article(article, response):
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
