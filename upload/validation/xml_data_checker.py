import sys

from django.utils.translation import gettext as _
from packtools.sps.validation import xml_validator as packtools_xml_data_checker
from upload.models import (
    XMLError,
    XMLErrorReport,
    XMLInfoReport,
    choices,
)


class XMLDataChecker:
    def __init__(self, package, journal, issue, params=None):
        self.error_report = None
        self.info_report = None
        self.package = package
        self.user = package.creator
        self.journal = journal
        self.issue = issue
        self.xmltree = package.xml_with_pre.xmltree
        self.params = {}
        self.params.update(params or {})
        self.params.update(self.get_journal_params())

    def get_journal_params(self):
        try:
            return {
                # "get_doi_data": callable_get_doi_data,
                "doi_required": self.journal.doi_prefix,
                "expected_toc_sections": self.journal.toc_sections,
                "journal_acron": self.journal.journal_acron,
                "publisher_name_list": self.journal.publisher_names,
                "nlm_ta": self.journal.nlm_title,
                "journal_license_code": self.journal.license_code,
            }
        except Exception as e:
            return {}

    def create_info_report(self):
        self.info_report = XMLInfoReport.create_or_update(
            self.user,
            self.package,
            _("XML Info Report"),
            choices.VAL_CAT_XML_CONTENT,
            reset_validations=True,
        )

    def create_error_report(self, report_name):
        return XMLErrorReport.create_or_update(
            self.user,
            self.package,
            _("XML Error Report") + f': {report_name}',
            choices.VAL_CAT_XML_CONTENT,
            reset_validations=True,
        )

    def validate(self):
        try:
            operation = self.package.start(self.user, "xml data validation")
            XMLError.objects.filter(report__package=self.package).delete()

            for group, results in packtools_xml_data_checker.validate_xml_content(
                self.xmltree, self.params
            ):
                try:
                    for index, result in enumerate(results):
                        self._handle_result(group, result, index)
                except Exception as exc:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    self._handle_exception({"group": group, "exception": exc, "exc_traceback": exc_traceback})

            # devido às tarefas serem executadas concorrentemente,
            # necessário registrar as tarefas finalizadas
            if self.info_report:
                self.info_report.finish_validations()

            for error_report in self.package.xml_error_report.all():
                if error_report.xml_error.count():
                    error_report.finish_validations()
                else:
                    error_report.delete()

            return True
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            operation = self.package.start(self.user, f"result {index}")
            detail = {}
            detail.update(result)
            detail["len"] = {k: len(v) for k, v in result.items() if v}
            operation.finish(
                self.user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
                detail=detail,
            )

    def _handle_result(self, group, result, index):
        try:
            status_ = result["response"]
            subject = group
            if status_ == "OK":
                if not self.info_report:
                    self.create_info_report()
                report = self.info_report
            else:
                report = self.create_error_report(group or '')

            validation_result = report.add_validation_result(
                status=status_,
                message=result.get("message"),
                data=result,
                subject=subject,
            )
            attribute = "/".join([item for item in (result.get("item"), result.get("sub_item")) if item])
            validation_result.focus = result.get("title")
            validation_result.attribute = attribute
            validation_result.parent = result.get("parent")
            validation_result.parent_id = result.get("parent_id")
            validation_result.parent_article_type = result.get("parent_article_type")
            validation_result.validation_type = result.get("validation_type") or "xml"

            if status_ != "OK":
                validation_result.advice = result.get("advice")
                validation_result.expected_value = result.get("expected_value")
                validation_result.got_value = result.get("got_value")
                validation_result.reaction = choices.ER_REACTION_FIX

            validation_result.save()
            return validation_result
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            operation = self.package.start(self.user, f"result {index}")
            detail = {}
            detail.update(result)
            detail["len"] = {k: len(v) for k, v in result.items() if v}
            operation.finish(
                self.user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
                detail=detail,
            )

    def _handle_exception(self, result):
        group = result.get("group") or "configuration"
        operation = self.package.start(self.user, f"{group} exception")
        operation.finish(
            self.user,
            completed=False,
            exception=result.get("exception"),
            exc_traceback=result.get("exc_traceback"),
        )