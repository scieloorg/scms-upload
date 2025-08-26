import os
import logging
import sys
import traceback

from django.db.models import Q
from django.utils.translation import gettext as _
from packtools.sps.models.dates import ArticleDates
from packtools.sps.models.front_articlemeta_issue import ArticleMetaIssue
from packtools.sps.models.journal_meta import ISSN, Title
from packtools.sps.pid_provider.xml_sps_lib import GetXMLItemsError, XMLWithPre

from article import choices as article_choices
from article.models import Article
from issue.models import Issue
from journal.models import Journal
from package.models import update_zip_file
from pid_provider.requester import PidRequester
from proc.controller import create_or_update_journal, create_or_update_issue

from tracker.models import UnexpectedEvent
from upload.models import (
    Package,
    ValidationReport,
    choices,
)
from upload.utils import file_utils, xml_utils

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
                package.finish_reception(
                    blocking_error_status=response.get("package_status")
                )
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
            _(
                "Not allowed to accept new package. There is a previous package which status={}. Search it and change the status to '{}'"
            ).format(previous_package.status, choices.PS_PENDING_CORRECTION)
        )

    if article:
        if article.status == article_choices.AS_REQUIRE_UPDATE:
            response["package_category"] = choices.PC_UPDATE
        elif article.status == article_choices.AS_REQUIRE_ERRATUM:
            response["package_category"] = choices.PC_ERRATUM
        else:
            response["package_category"] = choices.PC_UPDATE

            raise UnexpectedPackageError(
                _(
                    "Not allowed to accept new package. There is a previous package which status={}. Search it and change the status to '{}'"
                ).format(article.status, choices.PS_PENDING_CORRECTION)
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
    Package.objects.filter(**params, status=choices.PS_PENDING_CORRECTION).update(
        status=choices.PS_ARCHIVED
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
            similar_journals = _("Registered journals: {}. ").format(similar_journals)
        else:
            similar_journals = _("Found no registered journal. ")
        raise PackageDataError(
            _(
                "Journal in XML must be a registered journal. Journal in XML: {}. {}. Register the journal on core.scielo.org"
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
            issues = _("Registered issues: {}. ").format(issues)
        else:
            issues = _("{} has no registered issues").format(response["journal"])
        raise PackageDataError(
            _(
                "Issue in XML must be a registered issue. Issue in XML {}. {}. Register the issue on core.scielo.org"
            ).format(data, issues)
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
