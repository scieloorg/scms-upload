import os
import logging
import sys
import traceback

from django.db.models import Q
from django.utils.translation import gettext_lazy as _
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
from proc.controller import (
    fetch_and_create_journal,
    fetch_and_create_issues,
    FetchJournalDataException,
    FetchIssueDataException,
)

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


class JournalDataChecker:
    """Consulta e valida dados de journal usando dados locais e API do core."""

    def __init__(self, xmltree, user):
        self._user = user
        self._parse_xml(xmltree)
        self.core_communication_error = False

    def _parse_xml(self, xmltree):
        """Extrai dados de journal do XML."""
        xml = Title(xmltree)
        self.journal_title = xml.journal_title

        xml = ISSN(xmltree)
        self.issn_electronic = xml.epub
        self.issn_print = xml.ppub

    def get_local(self):
        """Consulta dados locais de journal."""
        return Journal.get_registered(
            self.journal_title, self.issn_electronic, self.issn_print
        )

    def fetch_from_core(self):
        """Consulta dados remotos de journal e atualiza os dados locais."""
        try:
            fetch_and_create_journal(
                self._user,
                issn_electronic=self.issn_electronic,
                issn_print=self.issn_print,
                force_update=True,
            )
        except FetchJournalDataException as e:
            self.core_communication_error = True
            logging.warning(f"Core API communication failure for journal: {e}")

    def get_or_fetch(self):
        """Consulta dados locais; se inexistentes, consulta o core e tenta novamente."""
        # 1. consulta dados locais de journal
        try:
            return self.get_local()
        except Journal.DoesNotExist:
            pass

        # 2. dados locais inexistentes, consulta dados remotos de journal
        # e atualiza os dados locais com os dados remotos
        self.fetch_from_core()

        # 3. consulta dados locais novamente após a tentativa de busca remota
        try:
            return self.get_local()
        except Journal.DoesNotExist:
            return None

    def _build_similar_journals_msg(self):
        """Monta mensagem com journals similares para diagnóstico."""
        similar_journals = []
        for j in Journal.get_similar_items(
            self.journal_title, self.issn_electronic, self.issn_print
        ):
            similar_journals.append(
                {
                    "journal_title": j.title,
                    "issn_electronic": j.official_journal.issn_electronic,
                    "issn_print": j.official_journal.issn_print,
                }
            )
        if similar_journals:
            return _("Registered journals: {}. ").format(similar_journals)
        return _("Found no registered journal. ")

    def raise_error(self):
        """Monta e lança erro com informações detalhadas."""
        data = {
            "journal_title": self.journal_title,
            "issn_electronic": self.issn_electronic,
            "issn_print": self.issn_print,
        }
        similar_journals = self._build_similar_journals_msg()

        if self.core_communication_error:
            raise PackageDataError(
                _(
                    "CORE COMMUNICATION FAILURE: Could not verify journal data. "
                    "The core API is unreachable. "
                    "Journal in XML: {}. {}"
                ).format(data, similar_journals)
            )
        raise PackageDataError(
            _(
                "Journal in XML must be a registered journal. "
                "Journal in XML: {}. {}. "
                "Register the journal on core.scielo.org"
            ).format(data, similar_journals)
        )

    def check(self, response):
        """Executa a verificação completa de journal e atualiza response."""
        journal = self.get_or_fetch()
        if journal:
            response["journal"] = journal
            return

        response["journal"] = None
        if self.core_communication_error:
            response["core_communication_error"] = True
        self.raise_error()

    def refresh(self, response):
        """Consulta dados remotos de journal e atualiza response."""
        self.fetch_from_core()
        if self.core_communication_error:
            response["core_communication_error"] = True
            return

        # consulta dados locais após a atualização remota
        try:
            response["journal"] = self.get_local()
        except Journal.DoesNotExist:
            pass


class IssueDataChecker:
    """Consulta e valida dados de issue usando dados locais e API do core."""

    def __init__(self, xmltree, user, journal):
        self._user = user
        self._journal = journal
        self._parse_xml(xmltree)
        self.core_communication_error = False

    def _parse_xml(self, xmltree):
        """Extrai dados de issue do XML."""
        xml = ArticleDates(xmltree)
        try:
            self.publication_year = xml.collection_date["year"]
        except (TypeError, KeyError, ValueError):
            try:
                self.publication_year = xml.article_date["year"]
            except (TypeError, KeyError, ValueError):
                self.publication_year = None

        xml = ArticleMetaIssue(xmltree)
        self.volume = xml.volume
        self.suppl = xml.suppl
        self.number = xml.number

    def get_local(self):
        """Consulta dados locais de issue."""
        return Issue.get(
            journal=self._journal,
            volume=self.volume,
            supplement=self.suppl,
            number=self.number,
        )

    def fetch_from_core(self):
        """Consulta dados remotos de issue e atualiza os dados locais."""
        try:
            fetch_and_create_issues(
                self._journal,
                self.publication_year,
                self.volume,
                self.suppl,
                self.number,
                self._user,
            )
        except FetchIssueDataException as e:
            self.core_communication_error = True
            logging.warning(f"Core API communication failure for issue: {e}")

    def get_or_fetch(self):
        """Consulta dados locais; se inexistentes, consulta o core e tenta novamente."""
        # 1. consulta dados locais de issue
        try:
            return self.get_local()
        except Issue.DoesNotExist:
            pass

        # 2. dados locais inexistentes, consulta dados remotos de issue
        # e atualiza os dados locais com os dados remotos
        self.fetch_from_core()

        # 3. consulta dados locais novamente após a tentativa de busca remota
        try:
            issue = self.get_local()
            logging.info(f"issue: {issue}")
            return issue
        except Issue.DoesNotExist:
            return None

    def _build_similar_issues_msg(self):
        """Monta mensagem com issues similares para diagnóstico."""
        items = None
        if self.publication_year and self.volume:
            items = Issue.objects.filter(
                Q(publication_year=self.publication_year) | Q(volume=self.volume),
                journal=self._journal,
            )
        elif self.publication_year:
            items = Issue.objects.filter(
                Q(publication_year=self.publication_year), journal=self._journal
            )
        if not items or not items.count():
            items = Issue.objects.filter(journal=self._journal)

        issues = []
        for item in items.order_by("-publication_year"):
            issues.append(
                {
                    "publication_year": self.publication_year,
                    "volume": item.volume,
                    "number": item.number,
                    "supplement": item.supplement,
                }
            )
        if issues:
            return _("Registered issues: {}. ").format(issues)
        return _("{} has no registered issues").format(self._journal)

    def raise_error(self):
        """Monta e lança erro com informações detalhadas."""
        data = {
            "journal": self._journal,
            "volume": self.volume,
            "number": self.number,
            "suppl": self.suppl,
            "publication_year": self.publication_year,
        }
        logging.info(f"IssueDataChecker.raise_error {data}")
        similar_issues = self._build_similar_issues_msg()

        if self.core_communication_error:
            raise PackageDataError(
                _(
                    "CORE COMMUNICATION FAILURE: Could not verify issue data. "
                    "The core API is unreachable. "
                    "Issue in XML: {}. {}"
                ).format(data, similar_issues)
            )
        raise PackageDataError(
            _(
                "Issue in XML must be a registered issue. "
                "Issue in XML {}. {}. "
                "Register the issue on core.scielo.org"
            ).format(data, similar_issues)
        )

    def check(self, response):
        """Executa a verificação completa de issue e atualiza response."""
        issue = self.get_or_fetch()
        if issue:
            response["issue"] = issue
            return

        response["issue"] = None
        if self.core_communication_error:
            response["core_communication_error"] = True
        self.raise_error()

    def refresh(self, response):
        """Consulta dados remotos de issue e atualiza response."""
        self.fetch_from_core()
        if self.core_communication_error:
            response["core_communication_error"] = True
            return

        # consulta dados locais após a atualização remota
        try:
            response["issue"] = self.get_local()
        except Issue.DoesNotExist:
            pass


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

        journal_checker = JournalDataChecker(xmltree, user)
        journal_checker.check(response)
        logging.info(f"JournalDataChecker.check: {response}")

        issue_checker = IssueDataChecker(xmltree, user, response["journal"])
        issue_checker.check(response)
        logging.info(f"IssueDataChecker.check: {response}")

        # verifica a consistência dos dados de journal e issue
        # no XML e na base de dados
        _check_xml_and_registered_data_compability(
            response, journal_checker, issue_checker
        )
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


def _check_xml_and_registered_data_compability(
    response, journal_checker, issue_checker
):
    article = response["article"]

    if article:
        journal = response["journal"]
        if not journal == article.journal:
            # divergência detectada - consulta dados remotos de journal
            journal_checker.refresh(response)
            journal = response["journal"]

            # re-verifica após a tentativa de atualização
            if not journal == article.journal:
                error_msg = _("{} (registered, {}) differs from {} (XML, {})").format(
                    article.journal, article.journal.id, journal, journal.id
                )
                if response.get("core_communication_error"):
                    error_msg = _(
                        "CORE COMMUNICATION FAILURE: {}. "
                        "Could not refresh data from core API"
                    ).format(error_msg)
                raise PackageDataError(error_msg)

        issue = response["issue"]
        if not issue == article.issue:
            # divergência detectada - consulta dados remotos de issue
            issue_checker.refresh(response)
            issue = response["issue"]

            # re-verifica após a tentativa de atualização
            if not issue == article.issue:
                error_msg = _("{} (registered, {}) differs from {} (XML, {})").format(
                    article.issue, article.issue.id, issue, issue.id
                )
                if response.get("core_communication_error"):
                    error_msg = _(
                        "CORE COMMUNICATION FAILURE: {}. "
                        "Could not refresh data from core API"
                    ).format(error_msg)
                raise PackageDataError(error_msg)
