import logging
import os
from functools import partial

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from packtools.sps.pid_provider.xml_sps_lib import (
    GetXMLItemsError,
    GetXmlWithPreError,
    XMLWithPre,
)

from article import choices as article_choices
from article.authorization import is_public_article
from article.models import CHANGE_REQUEST_REQUIRED, Article
from issue.models import Issue
from journal.models import Journal
from package.models import update_zip_file
from pid_provider.requester import PidRequester
from proc.controller import IssueDataChecker, JournalDataChecker
from team.models import get_user_membership_ids
from upload.article_changes import prepare_change_requests
from upload.models import (
    NEWER_DOCUMENT,
    Package,
    PkgValidationResult,
    UploadProcResult,
    ValidationReport,
    choices,
)
from upload.utils import file_utils, xml_utils
from upload.validation.article_changes import normalize_doi

pp = PidRequester()


class UnexpectedPackageError(Exception):
    ...


class PackageDataError(Exception):
    ...


class UploadJournalDataChecker(JournalDataChecker):
    """Extensão de JournalDataChecker com funcionalidades específicas do fluxo de upload."""

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


class UploadIssueDataChecker(IssueDataChecker):
    """Extensão de IssueDataChecker com funcionalidades específicas do fluxo de upload."""

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
        if items is None or not items.exists():
            items = Issue.objects.filter(journal=self._journal)

        issues = []
        for item in items.order_by("-publication_year"):
            issues.append(
                {
                    "publication_year": item.publication_year,
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


def reject_change_packages(user, packages, error):
    message = "; ".join(error.messages)
    for package in packages:
        if package.public_ws_status == choices.PUBLISHED:
            continue
        previous_results = list(
            PkgValidationResult.objects.filter(report__package=package).values(
                "report_id", "report__title", "status", "message", "data"
            )
        )
        if previous_results:
            event = UploadProcResult.create(
                user, package, "Reception diagnostics preserved"
            )
            event.finish(
                user, completed=True, detail={"validation_results": previous_results}
            )
        report = ValidationReport.create_or_update(
            user,
            package,
            gettext_noop("Article change package"),
            choices.VAL_CAT_GROUP_DATA,
            reset_validations=True,
        )
        report.add_validation_result(
            status=choices.VALIDATION_RESULT_BLOCKING,
            message=message,
            subject=gettext_noop("Article change package"),
        )
        report.finish_validations()
        package.status = choices.PS_UNEXPECTED
        package.calculate_validation_numbers()
    return {
        "error_message": message,
        "error_level": choices.VALIDATION_RESULT_BLOCKING,
        "package_status": choices.PS_UNEXPECTED,
    }


def record_reception_failure(user, packages, error):
    for package in packages:
        package.refresh_from_db()
        event = UploadProcResult.create(user, package, "Package reception failed")
        event.finish(user, completed=False, exception=error)
        if package.public_ws_status != choices.PUBLISHED:
            Package.objects.filter(pk=package.pk).update(status=choices.PS_UNEXPECTED)


@transaction.atomic
def prepare_package_reception(user, packages, task, retry_package_id=None):
    """Prepare a submission once, then enqueue only the selected documents."""
    packages = list(packages)
    if not packages:
        return
    selected = packages
    if retry_package_id:
        target = next(package for package in packages if package.pk == retry_package_id)
        if target.status != choices.PS_SUBMITTED:
            return
    if packages[0].pkg_zip_id:
        prepare_change_requests(user, packages)
    if retry_package_id:
        request_ids = target.change_requests.values_list("pk", flat=True)
        related_ids = set(
            Package.objects.filter(
                pkg_zip_id=target.pkg_zip_id, change_requests__pk__in=request_ids
            ).values_list("pk", flat=True)
        )
        selected = [
            package
            for package in packages
            if package.pk == target.pk
            or (package.pk in related_ids and package.has_interrupted_reception)
        ]

    for package in selected:
        if not package.can_receive_package(user):
            raise ValidationError(
                _("The depositor is not authorized for the original article.")
            )
        if package.has_newer_accepted_attempt():
            raise ValidationError(NEWER_DOCUMENT)
        if not package.file or not package.file.storage.exists(package.file.name):
            raise ValidationError(_("The submitted ZIP is no longer available."))

    for package in selected:
        if retry_package_id and package.pk != retry_package_id:
            attempt = UploadProcResult.create(user, package, "Try processing")
            attempt.detail = {
                "state": "queued",
                "previous_status": package.status,
                "validation_results": list(
                    package.validation_report.values(
                        "id",
                        "title",
                        "pkg_validation_result__status",
                        "pkg_validation_result__message",
                        "pkg_validation_result__data",
                    )
                ),
            }
            attempt.save(update_fields=["detail"])
        package.status = choices.PS_ENQUEUED_FOR_VALIDATION
        package.updated_by = user
        package.save(update_fields=["status", "updated_by", "updated"])
        transaction.on_commit(
            partial(task.apply_async, kwargs={"user_id": user.pk, "pkg_id": package.pk})
        )


@transaction.atomic
def receive_package(user, package):
    try:
        zip_xml_file_path = package.file.path
        response = {}
        for xml_with_pre in XMLWithPre.create(path=zip_xml_file_path):

            package.main_doi = xml_with_pre.main_doi
            package.add_order(xml_with_pre.order, xml_with_pre.fpage)
            package.save()

            response = _check_article_and_journal(package, xml_with_pre, user=user)
            logging.info(response)

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
                    title=gettext_noop("Package file"),
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

            if response.get("v3") and not xml_with_pre.v3:
                xml_with_pre.v3 = response["v3"]
            if response.get("v2") and not xml_with_pre.v2:
                xml_with_pre.v2 = response["v2"]
            update_zip_file(zip_xml_file_path, xml_with_pre.filename, xml_with_pre)

            if package.article and not package.change_role:
                package.article.update_status()

            # Old reception diagnostics have been preserved in the retry event.
            PkgValidationResult.objects.filter(
                report__package=package,
                report__title__in=(
                    "Package file",
                    "Article change package",
                    "File Report",
                ),
            ).delete()
            package.accept_document_version(response.get("previous_package_id"))
            _record_authorship_change(user, package, xml_with_pre)
            return response
    except (GetXMLItemsError, GetXmlWithPreError):
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
        gettext_noop("File Report"),
        choices.VAL_CAT_PACKAGE_FILE,
        reset_validations=True,
    )
    report.add_validation_result(
        status=choices.VALIDATION_RESULT_FAILURE,
        message=message,
        data=data,
    )
    return {"error_message": message, "error_level": choices.VALIDATION_RESULT_BLOCKING}


def _check_article_and_journal(package, xml_with_pre, user):
    response = {}
    try:
        xmltree = xml_with_pre.xmltree

        journal_checker = UploadJournalDataChecker.from_xmltree(xmltree, user)
        journal_checker.check(response)
        logging.info(f"UploadJournalDataChecker.check: {response}")
        journal = response.get("journal")

        membership = get_user_membership_ids(user)
        if (
            not user
            or not getattr(user, "is_authenticated", False)
            or not user.is_active
            or (
                not user.is_superuser
                and (
                    not journal
                    or journal.id not in membership.get("journal_list_ids", [])
                )
            )
        ):
            journal_title = journal.title if journal else _("Unknown")
            raise UnexpectedPackageError(
                _("User is not authorized to submit packages for journal '{}'.").format(
                    journal_title
                )
            )

        # Serialize acceptance of versions of a document, including first deposits.
        # The lock is retained through the successful package save in receive_package.
        if transaction.get_connection().in_atomic_block:
            Journal.objects.select_for_update().get(pk=journal.pk)

        article = Article.identify(
            pid_v3=xml_with_pre.v3,
            pid_v2=xml_with_pre.v2,
            doi=normalize_doi(xml_with_pre.main_doi),
            collection_acron=xml_with_pre.collection,
        )
        if article is not None:
            response.update(v3=article.pid_v3, v2=article.pid_v2, registered=True)
        else:
            response.update(
                pp.is_registered_xml_with_pre(xml_with_pre, xml_with_pre.filename)
            )
            if response.get("error_type"):
                raise PackageDataError(response.get("error_msg"))
            if response.get("v3"):
                article = Article.objects.filter(pid_v3=response["v3"]).first()

        logging.info(f"is_registered_xml_with_pre: {response}")

        name, ext = os.path.splitext(xml_with_pre.filename)
        _check_package_is_expected(response, package, name, article, user=user)
        logging.info(f"_check_package_is_expected: {response}")

        issue_checker = UploadIssueDataChecker.from_xmltree(
            xmltree, user, response["journal"]
        )
        issue_checker.check(response)
        logging.info(f"UploadIssueDataChecker.check: {response}")

        _check_xml_and_registered_data_compatibility(
            response, journal_checker, issue_checker
        )
        logging.info(f"_check_xml_and_registered_data_compatibility: {response}")
        response["package_status"] = choices.PS_ENQUEUED_FOR_VALIDATION

        return response
    except Exception as error:
        response.update(
            package_status=(
                choices.PS_UNEXPECTED
                if isinstance(error, (UnexpectedPackageError, ValidationError))
                else choices.PS_PENDING_CORRECTION
            ),
            error_message=str(error),
            error_level=choices.VALIDATION_RESULT_BLOCKING,
        )
        return response


def _check_package_is_expected(response, package, sps_pkg_name, article, user=None):
    if article is not None:
        actor = user or package.creator
        if not actor or not actor.is_active or (
            not actor.is_superuser
            and article.journal_id not in get_user_membership_ids(actor).get("journal_list_ids", [])
        ):
            raise UnexpectedPackageError(_("The depositor is not authorized for the registered article."))

    if package.has_newer_accepted_attempt(
        article=article, name=sps_pkg_name, journal=response.get("journal")
    ):
        raise UnexpectedPackageError(NEWER_DOCUMENT)
    previous_package = (
        package.other_document_attempts(
            article=article, name=sps_pkg_name, journal=response.get("journal")
        )
        .exclude(status=choices.PS_ARCHIVED)
        .order_by("-created", "-pk")
        .first()
    )
    response["previous_package_id"] = previous_package.pk if previous_package else None

    response["article"] = article

    change_request = package.change_requests.filter(
        submission_id=package.pkg_zip_id,
        status=article_choices.RCS_RECEIVED,
    ).first()
    if change_request:
        if package.change_role == choices.CPR_ORIGINAL:
            if article is not None and article.pk != change_request.article_id:
                raise UnexpectedPackageError(_("The received original differs from the authorized article."))
            response["article"] = change_request.article
        response["package_category"] = change_request.change_type
        return

    if package.change_role:
        raise UnexpectedPackageError(CHANGE_REQUEST_REQUIRED)

    if article:
        if is_public_article(article):
            raise UnexpectedPackageError(CHANGE_REQUEST_REQUIRED)
        response["package_category"] = choices.PC_UPDATE
    else:
        response["package_category"] = choices.PC_NEW_DOCUMENT
        return


def _record_authorship_change(user, package, document):
    previous = package.previous_package
    if previous is None:
        return
    try:
        previous_document = previous.xml_with_pre
    except (OSError, ValueError, GetXMLItemsError, GetXmlWithPreError):
        return
    if previous_document is None or previous_document.authors == document.authors:
        return

    report = ValidationReport.create_or_update(
        user,
        package,
        gettext_noop("Document identity"),
        choices.VAL_CAT_GROUP_DATA,
        reset_validations=True,
    )
    report.add_validation_result(
        status=choices.VALIDATION_RESULT_INFO,
        message=_("Document authorship changed. Review the updated authors."),
        subject=gettext_noop("Document identity"),
        data={"previous": previous_document.authors, "submitted": document.authors},
    )
    report.finish_validations()


def _check_xml_and_registered_data_compatibility(
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
