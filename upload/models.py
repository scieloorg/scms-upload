import traceback
import sys
import csv
import logging
import os
from datetime import date, datetime, timedelta
from random import randint
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import IntegrityError, models
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from packtools.sps.pid_provider.xml_sps_lib import (
    XMLWithPre,
    XMLWithPreArticlePublicationDateError,
    update_zip_file_xml,
    get_zips,
)
from wagtail.admin.panels import (
    FieldPanel,
    InlinePanel,
    MultiFieldPanel,
    ObjectList,
    TabbedInterface,
)
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from article import choices as article_choices
from article.models import Article

from collection.models import Collection
from collection import choices as collection_choices
from core.models import CommonControlField
from issue.models import Issue
from package import choices as package_choices
from package.models import SPSPkg
from proc.models import IssueProc, JournalProc, Operation
from team.models import CollectionTeamMember
from upload import choices
from upload.forms import (
    ReadyToPublishPackageForm,
    QAPackageForm,
    UploadPackageForm,
    UploadValidatorForm,
    ValidationResultForm,
    XMLErrorReportForm,
    PackageZipForm,
)
from upload.permission_helper import ACCESS_ALL_PACKAGES, ASSIGN_PACKAGE, FINISH_DEPOSIT
from upload.utils import file_utils
from upload.utils.package_utils import update_zip_file
from upload.utils.zip_pkg import PkgZip


class PublishingPrepException(Exception):
    pass


class NotFinishedValitionsError(Exception): ...


User = get_user_model()


class UploadProcResult(Operation, Orderable):
    proc = ParentalKey("Package", related_name="upload_proc_result")


def calculate_percentage(value, total):
    return round(value * 100 / total, 2)


def _get_numbers():
    return {
        "total_blocking": 0,
        "total_critical": 0,
        "total_error": 0,
        "total_warning": 0,
    }


def report_datetime():
    return datetime.utcnow().strftime("%Y-%d-%m-%H%M%S")


def upload_package_directory_path(instance, filename):
    name, ext = os.path.splitext(filename)
    try:
        sps_pkg_name = instance.name
    except AttributeError:
        sps_pkg_name = instance.package.name

    subdirs = (sps_pkg_name or name).split("-")
    subdir_sps_pkg_name = "/".join(subdirs)

    return f"upload/{subdir_sps_pkg_name}/{ext[1:]}/{filename}"


class PackageZip(CommonControlField):
    verbose_name = _("Package Zip")

    file = models.FileField(
        _("Package Zip File"),
        upload_to=upload_package_directory_path,
        null=False,
        blank=False,
    )
    show_package_validations = models.BooleanField(
        _("Show package validations"),
        default=False,
        help_text=_(
            "Unchecked to be redirect to package upload. Checked to be redirect to package validation"
        ),
    )
    name = models.CharField(max_length=40, null=True, blank=True)

    panels = [
        FieldPanel("file"),
        FieldPanel("show_package_validations"),
    ]

    base_form_class = PackageZipForm

    class Meta:
        verbose_name = _("Zip file")
        verbose_name_plural = _("Zip files")
        indexes = [
            models.Index(
                fields=[
                    "name",
                ]
            ),
        ]

    def __str__(self):
        return self.file.name

    def save_file(self, filename=None, content=None):
        if not content:
            raise ValueError("PackageZip.save_file requires content")
        filename = filename or os.path.basename(self.file.path)
        try:
            self.file.delete(save=True)
        except Exception as e:
            logging.exception(f"Unable to delete {self.file.path} {e} {type(e)}")
        self.file.save(filename, ContentFile(content))

    @property
    def xmls(self):
        for item in XMLWithPre.create(path=self.file.path):
            logging.info(item.filename)
            yield item.filename

    def split(self, user):
        pkg_zip = PkgZip(self.file.path)
        for item in pkg_zip.split():
            if item.get("error"):
                yield item
            else:
                key = item["xml_name"]
                yield {
                    "xml_name": key,
                    "package": Package.create_or_update(
                        user,
                        key,
                        self,
                        key + ".zip",
                        item["content"]
                    ),
                }


class Package(CommonControlField, ClusterableModel):
    pkg_zip = models.ForeignKey(
        PackageZip,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="packages",
    )
    file = models.FileField(
        _("Package File"),
        upload_to=upload_package_directory_path,
        null=False,
        blank=False,
    )
    main_doi = models.CharField(_("DOI"), max_length=128, null=True, blank=True)
    name = models.CharField(_("SPS Package name"), max_length=40, null=True, blank=True)
    signature = models.CharField(_("Signature"), max_length=32, null=True, blank=True)
    category = models.CharField(
        _("Category"),
        max_length=32,
        choices=choices.PACKAGE_CATEGORY,
        null=True,
        blank=True,
    )
    status = models.CharField(
        _("Status"),
        max_length=32,
        choices=choices.PACKAGE_STATUS,
        default=choices.PS_ENQUEUED_FOR_VALIDATION,
    )
    qa_decision = models.CharField(
        _("Quality analysis decision"),
        max_length=32,
        choices=choices.QA_DECISION,
        null=True,
        blank=True,
        help_text=_(
            "Make a decision about the package or choose the analyst who will decide it"
        ),
    )
    qa_comment = models.TextField(
        _("Quality analysis comment"),
        null=True,
        blank=True,
        help_text=_(
            "Comment the decision about the package or choose the analyst who will comment it"
        ),
    )
    analyst = models.ForeignKey(
        CollectionTeamMember,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        help_text=_(
            "Choose the analyst who will decide about the package or add your decision"
        ),
    )
    sps_pkg = models.ForeignKey(
        SPSPkg,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    article = models.ForeignKey(
        "article.Article",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    journal = models.ForeignKey(
        "journal.Journal", blank=True, null=True, on_delete=models.SET_NULL
    )
    issue = models.ForeignKey(
        "issue.Issue", blank=True, null=True, on_delete=models.SET_NULL
    )
    assignee = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL)
    expiration_date = models.DateField(_("Expiration date"), null=True, blank=True)
    numbers = models.JSONField(null=True, default=dict)
    critical_errors = models.PositiveSmallIntegerField(default=0)
    xml_errors_percentage = models.DecimalField(
        verbose_name=_("Error percentual"),
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text=_("0 to 100"),
    )
    xml_warnings_percentage = models.DecimalField(
        verbose_name=_("Warning percentual"),
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text=_("0 to 100"),
    )
    contested_xml_errors_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00, help_text=_("0 to 100")
    )
    declared_impossible_to_fix_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00, help_text=_("0 to 100")
    )
    order = models.PositiveSmallIntegerField(default=0, null=True, blank=True)
    pid_v2 = models.CharField(max_length=23, null=True, blank=True)
    linked = models.ManyToManyField(
        "Package",
        verbose_name=_("Linked packages"),
        help_text=_("Linked packages which will be published only if all are approved"),
        null=True,
        blank=True,
    )

    qa_ws_status = models.CharField(
        max_length=15,
        choices=choices.WEBSITE_STATUS,
        null=True,
        blank=True,
        default=choices.UNRELEASED,
    )
    qa_ws_pubdate = models.DateTimeField(null=True, blank=True)
    public_ws_status = models.CharField(
        max_length=15,
        choices=choices.WEBSITE_STATUS,
        null=True,
        blank=True,
        default=choices.UNRELEASED,
    )
    public_ws_pubdate = models.DateTimeField(null=True, blank=True)

    panels = [
        # FieldPanel("file"),
        FieldPanel("status", read_only=True),
        FieldPanel("numbers", read_only=True),
        FieldPanel("qa_ws_status", read_only=True),
        FieldPanel("public_ws_status", read_only=True),
    ]
    panel_event = [
        InlinePanel("upload_proc_result", label=_("Event newest to oldest")),
    ]
    edit_handler = TabbedInterface(
        [
            ObjectList(panels, heading=_("Status")),
            ObjectList(panel_event, heading=_("Events")),
        ]
    )
    base_form_class = UploadPackageForm

    class Meta:
        verbose_name = _("Package admin")
        verbose_name_plural = _("Package admin")
        permissions = (
            (FINISH_DEPOSIT, _("Can finish deposit")),
            (ACCESS_ALL_PACKAGES, _("Can access all packages from all users")),
            (ASSIGN_PACKAGE, _("Can assign package")),
        )
        indexes = [
            models.Index(
                fields=[
                    "pkg_zip",
                ]
            ),
            models.Index(
                fields=[
                    "category",
                ]
            ),
            models.Index(
                fields=[
                    "name",
                ]
            ),
            models.Index(
                fields=[
                    "status",
                ]
            ),
            models.Index(
                fields=[
                    "qa_decision",
                ]
            ),
            models.Index(
                fields=[
                    "xml_errors_percentage",
                ]
            ),
            models.Index(
                fields=[
                    "xml_warnings_percentage",
                ]
            ),
            models.Index(
                fields=[
                    "contested_xml_errors_percentage",
                ]
            ),
            models.Index(
                fields=[
                    "declared_impossible_to_fix_percentage",
                ]
            ),
            models.Index(
                fields=["main_doi"],
            ),
        ]

    @staticmethod
    def autocomplete_custom_queryset_filter(search_term: str):
        return Package.objects.filter(
            Q(pkg_zip__name__icontains=search_term)
            | Q(name__icontains=search_term)
            | Q(file__icontains=search_term)
        )

    def autocomplete_label(self):
        return f"{self.package_name} {self.status}"

    def __str__(self):
        if self.pkg_zip and self.pkg_zip.packages.all().count() > 1:
            return f"{self.package_name} ({self.pkg_zip.name})"
        return self.package_name

    def save(self, *args, **kwargs):
        if not self.expiration_date:
            self.expiration_date = date.today() + timedelta(days=30)

        if self.status == choices.PS_PENDING_CORRECTION and self.article:
            # volta article.status para o status antes da submissão do pacote
            self.article.update_status(rollback=True)

        super(Package, self).save(*args, **kwargs)

    @property
    def xml_with_pre(self):
        for item in XMLWithPre.create(path=self.file.path):
            return item

    @classmethod
    def get(cls, name, pkg_zip):
        return cls.objects.get(pkg_zip=pkg_zip, name=name)

    @classmethod
    def create(cls, user, name, pkg_zip, filename, file_content):
        try:
            obj = cls()
            obj.name = name
            obj.pkg_zip = pkg_zip
            obj.creator = user
            obj.save()
            obj.save_file(filename, file_content)
            logging.info(f"Saved {obj.id}")
            return obj
        except IntegrityError:
            return cls.get(name, pkg_zip)

    @classmethod
    def create_or_update(cls, user, name, pkg_zip, filename, file_content):
        try:
            obj = cls.get(name, pkg_zip)
            obj.updated_by = user

            obj.save_file(filename, file_content)
            return obj
        except cls.DoesNotExist:
            return cls.create(user, name, pkg_zip, filename, file_content)

    @property
    def xml(self):
        try:
            return self.xml_with_pre.tostring(pretty_print=True)
        except Exception as e:
            return f"<root>Unable to read xml file: {e}</root>"

    @property
    def renditions(self):
        """
        Retorna um gerador de itens com este formato
        {
            "name": name,
            "lang": item.language,
            "component_type": "rendition",
            "main": item.is_main_language,
            "content": b'',
        }
        """
        renditions = self.xml_with_pre.renditions

        with ZipFile(self.file.path) as zf:
            for rendition in renditions:
                rendition["content"] = zf.read(rendition["name"])
                yield rendition

    def files_list(self):
        try:
            return {"files": self.xml_with_pre.files}
        except file_utils.BadPackageFileError:
            return {"files": []}

    @property
    def is_published(self):
        return bool(self.article)

    @property
    def package_name(self):
        if self.name:
            return self.name
        return self.file.name

    # @classmethod
    # def get(cls, pkg_id=None, article=None):
    #     if pkg_id:
    #         return cls.objects.get(pk=pkg_id)
    #     if article:
    #         return cls.objects.get(article=article)

    @property
    def data(self):
        return dict(
            file=self.pkg_zip and self.pkg_zip.name,
            pkg_name=self.package_name,
            zip_name=self.pkg_zip and self.pkg_zip.name,
            status=self.status,
            category=self.category,
            journal=self.journal and self.journal.data,
            issue=self.issue and self.issue.data,
            article=self.article and self.article.data,
            assignee=str(self.assignee),
            expiration_date=self.expiration_date.isoformat()[:10],
        )

    @property
    def reports(self):
        for report in self.validation_report.order_by("created").all():
            yield report.data

    @property
    def xml_info_reports(self):
        for report in self.xml_info_report.order_by("created").all():
            yield report.data

    @property
    def xml_error_reports(self):
        for report in self.xml_error_report.order_by("created").all():
            yield report.data

    @property
    def is_validation_finished(self):
        if PkgValidationResult.objects.filter(
            report__package=self, status=choices.VALIDATION_RESULT_BLOCKING
        ).exists():
            return True
        if self.xml_info_report.filter(creation=choices.REPORT_CREATION_WIP).exists():
            return False
        if self.xml_error_report.filter(creation=choices.REPORT_CREATION_WIP).exists():
            return False
        if self.validation_report.filter(creation=choices.REPORT_CREATION_WIP).exists():
            return False
        return True

    def finish_reception(
        self, task_process_qa_decision=None, blocking_error_status=None
    ):
        """
        1. Verifica se as validações que executaram em paralelo, finalizaram
        2. Calcula os números de problemas do pacote
        3. Decide o próximo status:
        - PS_PENDING_CORRECTION: produtor de XML tem que corrigir
        - PS_VALIDATED_WITH_ERRORS: analista pode reavaliar e solicitar correção ou aprovar para a próxima etapa
        - PS_READY_TO_PREVIEW: sem problemas no pacote, será avaliada a apresentação

        Retorna:
            None
        """
        if not self.is_validation_finished:
            return

        self.calculate_validation_numbers()
        self.evaluate_validation_numbers(blocking_error_status)
        
        logging.info(f"Package.finish_reception - status: {self.status}")
        if self.status == choices.PS_READY_TO_PREVIEW:
            self.qa_decision = choices.PS_READY_TO_PREVIEW
            self.save()

            if task_process_qa_decision:
                task_process_qa_decision.apply_async(
                    kwargs=dict(
                        user_id=self.creator.id,
                        package_id=self.id,
                    )
                )

    def calculate_validation_numbers(self):
        """
        Calcula o total de errors, warnings, blocking errors, etc
        """
        pkg_numbers = PkgValidationResult.get_numbers(package=self)
        xml_numbers = XMLError.get_numbers(package=self)

        total_validations = (
            XMLInfo.get_numbers(package=self).get("total")
            + xml_numbers["total"]
            + pkg_numbers["total"]
        )
        self.critical_errors = pkg_numbers["total_critical"] + xml_numbers["total_critical"]

        self.xml_errors_percentage = calculate_percentage(xml_numbers["total_error"], total_validations)
        self.xml_warnings_percentage = calculate_percentage(xml_numbers["total_warning"], total_validations)
        self.contested_xml_errors_percentage = calculate_percentage(xml_numbers["reaction_not_to_fix"], xml_numbers["total"])
        self.declared_impossible_to_fix_percentage = calculate_percentage(xml_numbers["reaction_impossible_to_fix"], xml_numbers["total"])
        self.numbers = {
            "total_blocking": pkg_numbers["total_blocking"],
            "total_validations": total_validations,
            "total_xml_critical": xml_numbers["total_critical"],
            "total_xml_errors": xml_numbers["total_error"],
            "total_xml_warnings": xml_numbers["total_warning"],
            "total_xml_issues": xml_numbers["total"],
            "total_pkg_issues": pkg_numbers["total"],
        }
        self.save()

    @property
    def upload_validator(self):
        if not hasattr(self, '_upload_validator') or not self._upload_validor:
            self._upload_validor = UploadValidator.get()
        return self._upload_validor

    def evaluate_validation_numbers(self, blocking_error_status):
        self.status = self.upload_validator.get_pos_validation_status(
            self,
            blocking_error_status=blocking_error_status
        )
        self.save()

    @property
    def has_errors(self):
        return self.numbers.get("total_xml_issues") or self.numbers.get(
            "total_pkg_issues"
        )

    @property
    def metrics(self):
        metrics = {
            "critical_errors": self.critical_errors,
            "xml_errors_percentage": self.xml_errors_percentage,
            "xml_warnings_percentage": self.xml_warnings_percentage,
            "contested_xml_errors_percentage": self.contested_xml_errors_percentage,
            "declared_impossible_to_fix_percentage": self.declared_impossible_to_fix_percentage,
        }
        metrics.update(self.numbers or {})
        return metrics

    def get_conclusion(self):
        if self.status == choices.PS_PENDING_QA_DECISION:
            return _("The error review has been completed")

        if self.status == choices.PS_VALIDATED_WITH_ERRORS:
            return _("The error review is in progress")

        if self.status == choices.PS_PENDING_CORRECTION:
            return _("The XML package needs to be fixed and sent again")

        metrics = self.metrics
        if self.is_error_review_finished:
            msgs = []
            if metrics["total_contested_xml_errors"]:
                msgs.append(
                    _("It was concluded that {} are not errors").format(
                        metrics["total_contested_xml_errors"]
                    )
                )
            if metrics["total_declared_impossible_to_fix"]:
                msgs.append(
                    _("It was concluded that {} are impossible to fix").format(
                        metrics["total_declared_impossible_to_fix"]
                    )
                )
            if not self.is_acceptable_package:
                # <!-- User must finish the error review -->
                msgs.append(_("The XML package needs to be fixed and sent again"))

            else:
                msgs.append(_("Finish the deposit"))
            return ". ".join(msgs)
        else:
            return _("Review and comment the errors")

    @property
    def is_error_review_finished(self):
        if self.xml_error_report.count():
            return not self.xml_error_report.filter(xml_producer_ack=False).exists()

    @property
    def summary(self):
        data = {
            "is_validation_finished": self.is_validation_finished,
            "is_error_review_finished": self.is_error_review_finished,
            "is_acceptable_package": self.is_acceptable_package,
            "conclusion": self.get_conclusion(),
            "status": self.status,
        }
        data.update(self.metrics)
        return data

    def finish_deposit(self):
        """
        1. Analisa as respostas do produtor de XML aos problemas encontrados no pacote
        O produtor de XML pode concordar ou discordar com os erros
        2. O resultado decide o próximo status:
        - PS_PENDING_CORRECTION: os problemas foram confirmados e o produtor de XML tem que corrigi-los
        - PS_READY_TO_PREVIEW: pacote tem problemas toleráveis, será avaliada a apresentação

        Retorna:
            None
        """
        if not self.status == choices.PS_VALIDATED_WITH_ERRORS:
            return False

        metrics = self.metrics
        if metrics.get("reaction_to_fix"):
            # o produtor aceitar pelo menos 1 erro no XML,
            # fica pendente de correção, terminada ou não a revisão de erros
            self.status = choices.PS_PENDING_CORRECTION
            self.save()
            return True

        # terminada ou não a revisão de erros...
        if self.is_acceptable_package:
            # pode finalizar, se a quantidade de erros é tolerável
            # para passar para o próximo passo
            self.status = choices.PS_READY_TO_PREVIEW
            self.qa_decision = choices.PS_READY_TO_PREVIEW
            self.save()
            return True

        if not self.is_error_review_finished:
            # necessário finalizar a revisão de erros para definir status novo
            return False

        # revisão finalizada e a quantidade de erros não é tolerável
        self.status = choices.PS_PENDING_CORRECTION
        self.save()
        return True

    @property
    def is_acceptable_package(self):
        """
        Determina se o pacote é aceitável com base em vários critérios.

        Retorna:
            bool: True se o pacote for aceitável, False caso contrário.

        O pacote é considerado aceitável se:
        - Não houver erros bloqueadores.
        - O total de problemas for zero.
        - As porcentagens de erros e avisos XML estiverem dentro dos limites aceitáveis.
        - As porcentagens de erros XML contestados e declarados impossíveis de corrigir estiverem dentro dos limites aceitáveis.
        """
        return self.upload_validator.is_acceptable_package(self)

    def get_errors_report_content(self):
        filename = self.name + f"-{report_datetime()}-errors.csv"

        content = None
        fieldnames = ["package"]
        fieldnames.extend(XMLError.cols)

        with TemporaryDirectory() as targetdir:
            target = os.path.join(targetdir, filename)

            with open(target, "w", newline="") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for row in PkgValidationResult.rows(self, fieldnames):
                    writer.writerow(row)

                for row in XMLError.rows(self, fieldnames):
                    writer.writerow(row)

            # saved optimised
            with open(target, "rb") as fp:
                content = fp.read()

        return {"content": content, "filename": filename, "columns": fieldnames}

    def process_qa_decision(self, user):
        # (PS_DEPUBLISHED, _("Depublish")),
        # (PS_PENDING_CORRECTION, _("Pending for correction")),
        # (PS_PENDING_QA_DECISION, _("Pending quality analysis decision")),
        # (PS_READY_TO_PREVIEW, _("Ready to preview on QA website")),
        # (PS_READY_TO_PUBLISH, _("Ready to publish on public website")),

        operation = self.start(user, "process_qa_decision")

        if self.qa_decision in (
            choices.PS_PENDING_QA_DECISION, choices.PS_PENDING_CORRECTION
        ):
            self.register_qa_decision(
                user, operation, websites=None, result={}, rule=None
            )
            return []

        if self.qa_decision in (
            choices.PS_READY_TO_PREVIEW, choices.PS_READY_TO_PUBLISH,
        ):
            return self.prepare_to_publish(user, operation)

        if self.qa_decision == choices.PS_DEPUBLISHED:
            # TODO
            error = "not implemented"
        else:
            error = "unexpected decision"

        operation.finish(
            user,
            completed=True,
            detail={"decision": self.qa_decision, "error": error},
        )
        return []

    def analyze_sps_package(self):
        result = {"critical_errors": None, "errors": None, "warnings": None}

        if not self.sps_pkg.registered_in_core:
            result["critical_errors"] = [
                _("SPS package must be registered in the Core system")
            ]

        if not self.sps_pkg.valid_components:
            result["errors"] = []
            for component in self.sps_pkg.components.filter(uri=None):
                result["errors"].append(_("{} is not published on MinIO").format(component.basename))

        if not self.sps_pkg.valid_texts:
            result["warnings"] = []
            result["warnings"].append(_("Total of XML, PDF, HTML do not match {}").format(self.sps_pkg.texts))
        return result

    def has_publication_blockers(self):
        blocking_errors = []
        if self.linked and self.linked.filter(~Q(status=choices.PS_READY_TO_PUBLISH)).exists():
            blocking_errors.append(
                _("Packages linked - will publish together when all ready")
            )
        if self.is_acceptable_package:
            if self.upload_validator.rule == choices.MANUAL_PUBLICATION:
                blocking_errors.append(
                    _("Packages linked - will publish together when all ready"),
                )
        else:
            blocking_errors.append(_("Total error limit exceeded"))
        return blocking_errors

    def register_qa_decision(self, user, operation, websites, result, rule):
        try:
            exception = result.pop("exception")
        except (KeyError, AttributeError, TypeError, ValueError):
            exception = None

        comments = [exception or '']
        for k in ("critical_errors", "errors", "warnings"):
            comments.extend(result.get(k) or [])
        
        if not self.qa_comment:
            self.qa_comment = "\n".join([str(item) for item in comments if item])

        if self.qa_comment:
            self.register_qa_comment_as_error(user)

        if result and result.get("request_correction"):
            self.qa_decision = choices.PS_PENDING_CORRECTION
            self.assignee = self.creator

        self.status = self.qa_decision
        self.save()

        detail = {"decision": self.qa_decision, "websites": websites, "rule": rule}
        detail.update(result or {})
        operation.finish(user, completed=True, detail=detail, exception=exception)

    def xml_file_changed_pub_date(self, xml_with_pre):
        """
        Atualiza data de publicação do artigo e/ou pid v2, se necessário
        """
        try:
            xml_pub_date = datetime.fromisoformat(xml_with_pre.article_publication_date)
        except Exception as e:
            xml_pub_date = None

        changed_date = None
        if self.article and self.article.first_publication_date:
            if xml_pub_date != self.article.first_publication_date:
                changed_date = self.article.first_publication_date
        elif not xml_pub_date:
            changed_date = datetime.utcnow()

        if changed_date:
            xml_with_pre.article_publication_date = {
                "year": changed_date.year,
                "month": changed_date.month,
                "day": changed_date.day,
            }
            return True

    def xml_file_changed_pid_v2(self, xml_with_pre):
        if not xml_with_pre.v2:
            xml_with_pre.v2 = self.get_or_generate_pid_v2()
            return True

    def get_or_generate_pid_v2(self):
        issue_pid = IssueProc.get_or_generate_issue_pid(self.issue)
        # Nota: order não é o mesmo que pid
        number = str(self.order or randint(0, 100000)).zfill(5)
        return f"S{issue_pid}{number}"

    def prepare_sps_package(self, user, xml_with_pre, xml_file_changed):
        # Aplica-se também para um pacote de atualização de um conteúdo anteriormente migrado
        # TODO components, texts
        if xml_file_changed:
            update_zip_file(self.file.path, xml_with_pre)

        if (
            # self.xml_file_changed(xml_with_pre, set_pub_date)
            xml_file_changed
            or not self.sps_pkg
            or not self.sps_pkg.valid_components
        ):

            texts = {
                "xml_langs": list(xml_with_pre.langs),
                "pdf_langs": [
                    rendition["lang"]
                    for rendition in xml_with_pre.renditions
                    if rendition["name"] in xml_with_pre.filenames
                ],
            }
            self.sps_pkg = SPSPkg.create_or_update(
                user,
                sps_pkg_zip_path=self.file.path,
                origin=package_choices.PKG_ORIGIN_UPLOAD,
                is_public=bool(self.article and self.article.is_public),
                original_pkg_components=xml_with_pre.components,
                texts=texts,
                article_proc=self,
            )
            self.save()

            if self.sps_pkg:
                self.create_or_update_article(user, save=True)

    def start(self, user, name):
        # self.save()
        # operation = Operation.start(user, name)
        # self.operations.add(operation)
        # return operation
        return UploadProcResult.start(user, self, name)

    def update_sps_pkg_status(self):
        # completou sps package
        # TODO melhora a atribuição do status
        pass

    def add_order(self, position=None, fpage=None):
        try:
            self.order = int(position or fpage)
        except (ValueError, TypeError):
            pass

    def create_or_update_article(self, user, save):
        try:
            logging.info(f"create_or_update_article - status: {self.status}")
            if not self.issue:
                raise ValueError("Unable to create or update article: missing issue")
            if not self.journal:
                raise ValueError("Unable to create or update article: missing journal")

            self.article = Article.create_or_update(
                user, self.sps_pkg, self.issue, self.journal, self.order
            )

            # atualizar package.order com article.order, cujo valor position or fpage
            self.order = self.article.position
            if save:
                self.save()
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            operation = self.start(user, "create_or_update_article")
            operation.finish(
                user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
            )

    # def update_status(self):
    #     if self.status == choices.PS_READY_TO_PREVIEW:
    #         self.status = choices.PS_PREVIEW
    #         self.save()
    #     elif self.status == choices.PS_READY_TO_PUBLISH:
    #         self.status = choices.PS_PUBLISHED
    #         self.save()
    #         self.article.update_status()
    def update_publication_stage(self, website_kind, completed):
        """
        Estabele o próxim estágio, após ser publicado no QA ou no Público
        """
        if completed:
            status = choices.PUBLISHED

            if website_kind == collection_choices.QA:
                self.qa_ws_status = status
                self.qa_ws_pubdate = datetime.utcnow()
                self.status = choices.PS_PREVIEW
                self.save()
                self.article.update_status(
                    new_status=article_choices.AS_PREPARE_TO_PUBLISH
                )
            elif website_kind == collection_choices.PUBLIC:
                self.public_ws_status = status
                self.public_ws_pubdate = datetime.utcnow()
                self.status = choices.PS_PUBLISHED
                self.save()
                self.article.update_status(new_status=article_choices.AS_PUBLISHED)

    @property
    def toc_sections(self):
        try:
            return str(self.article.multilingual_sections)
        except AttributeError:
            return None

    def save_file(self, filename=None, content=None):
        if not content:
            raise ValueError("Package.save_file requires content")
        filename = filename or os.path.basename(self.file.path)
        try:
            self.file.delete(save=True)
        except Exception as e:
            pass
        self.file.save(filename, ContentFile(content))

    def register_qa_comment_as_error(self, user, data=None):
        data = data or {}
        data.update({"qa_decision": self.qa_decision})
        report_title = _("QA decision report")
        category = choices.VAL_CAT_QA_CONCLUSION
        report = ValidationReport.create_or_update(
            user,
            self,
            report_title,
            category,
            reset_validations=False,
        )
        validation_result = report.add_validation_result(
            status=choices.VALIDATION_RESULT_FAILURE,
            message=self.qa_comment,
            data=data,
            subject="qa decision",
        )
        report.creation = choices.REPORT_CREATION_DONE
        report.save()

    def prepare_to_publish(self, user, qa=None, public=None):
        # verifica se há impedimentos de tornar o artigo público
        blocking_errors = self.has_publication_blockers()
        block_public = bool(blocking_errors)

        if block_public:
            public = False

        if not qa and not public:
            return {}

        result = {}
        websites = []
        xml_changed = False
        xml_with_pre = self.xml_with_pre
        if qa:
            xml_changed = self.xml_file_changed_pid_v2(xml_with_pre)
            websites.append("QA")
            new_status = choices.PS_READY_TO_PREVIEW
        if public:
            xml_changed = self.xml_file_changed_pub_date(xml_with_pre)

        user = user or self.updated_by or self.creator
        self.prepare_sps_package(user, xml_with_pre, xml_changed)

        # valida o pacote sps
        result = self.analyze_sps_package()
        if result.get("blocking_errors"):
            return result

        if public and not self.sps_pkg.registered_in_core:
            result["blocking_errors"].append(
                _("SPS package requires PID provider registration")
            )
            websites.append("PUBLIC")
            new_status = choices.PS_READY_TO_PUBLISH

        return {"websites": websites, "result": result, "new_status": new_status}

    def publish(self, user, task_publish_article, websites):
        for website in websites:
            task_publish_article.apply_async(
                kwargs=dict(
                    user_id=user.id,
                    username=user.username,
                    api_data=api_data,
                    website_kind=website,
                    article_proc_id=None,
                    upload_package_id=self.id,
                )
            )
            if website == "PUBLIC":
                for item in self.linked.all():
                    task_publish_article.apply_async(
                        kwargs=dict(
                            user_id=user.id,
                            username=user.username,
                            api_data=api_data,
                            website_kind=website,
                            article_proc_id=None,
                            upload_package_id=item.id,
                        )
                    )

class QAPackage(Package):
    """
    XML validated with errors
    QA can approve or reject

    """

    panel_numbers = [
        FieldPanel("critical_errors", read_only=True),
        FieldPanel("xml_errors_percentage", read_only=True),
        FieldPanel("xml_warnings_percentage", read_only=True),
        FieldPanel("contested_xml_errors_percentage", read_only=True),
        FieldPanel("declared_impossible_to_fix_percentage", read_only=True),
        FieldPanel("status", read_only=True),
    ]
    panel_qa_decision = [
        FieldPanel("qa_decision"),
        FieldPanel("qa_comment"),
        AutocompletePanel("analyst"),
    ]
    panel_publication = [
        FieldPanel("order"),
        AutocompletePanel("linked"),
    ]
    panel_decision = panel_numbers + panel_qa_decision + panel_publication

    panel_event = [
        InlinePanel("upload_proc_result", label=_("Event newest to oldest")),
    ]
    edit_handler = TabbedInterface(
        [
            ObjectList(panel_decision, heading=_("Decision")),
            ObjectList(panel_event, heading=_("Events")),
        ]
    )
    base_form_class = QAPackageForm

    class Meta:
        proxy = True
        verbose_name = _("Quality control admin")
        verbose_name_plural = _("Quality control admin")


class ReadyToPublishPackage(Package):
    """
    Package ready to publish
    """

    panel_publication_status = [
        FieldPanel("qa_ws_status", read_only=True),
        FieldPanel("qa_ws_pubdate", read_only=True),
        FieldPanel("public_ws_status", read_only=True),
        FieldPanel("public_ws_pubdate", read_only=True),
    ]
    panel_qa_decision = [
        FieldPanel("analyst", read_only=True),
        FieldPanel("qa_decision"),
        FieldPanel("qa_comment"),
    ]
    panel_data = QAPackage.panel_numbers + panel_publication_status + panel_qa_decision + QAPackage.panel_publication

    panel_event = [
        InlinePanel("upload_proc_result", label=_("Event newest to oldest")),
    ]

    edit_handler = TabbedInterface(
        [
            ObjectList(panel_data, heading=_("Status")),
            ObjectList(panel_event, heading=_("Events")),
        ]
    )
    base_form_class = ReadyToPublishPackageForm

    class Meta:
        proxy = True
        verbose_name = _("Publication admin")
        verbose_name_plural = _("Publication admin")


class BaseValidationResult(CommonControlField):

    subject = models.CharField(
        _("Subject"),
        null=True,
        blank=True,
        max_length=128,
        help_text=_("Item being analyzed"),
    )
    data = models.JSONField(_("Data"), default=dict, null=True, blank=True)
    message = models.CharField(_("Message"), null=True, blank=True, max_length=500)
    status = models.CharField(
        _("Result"),
        max_length=8,
        choices=choices.VALIDATION_RESULT,
        default=choices.VALIDATION_RESULT_UNKNOWN,
        null=True,
        blank=True,
    )

    base_form_class = ValidationResultForm
    panels = [
        FieldPanel("subject", read_only=True),
        FieldPanel("status", read_only=True),
        FieldPanel("message", read_only=True),
        FieldPanel("data", read_only=True),
    ]

    cols = (
        "status",
        "subject",
        "message",
        "data"
    )
    # autocomplete_search_field = "subject"

    # def autocomplete_label(self):
    #     return self.row

    # def __str__(self):
    #     return "-".join(
    #         [
    #             self.subject,
    #             self.status,
    #         ]
    #     )

    class Meta:
        abstract = True
        verbose_name = _("Validation result")
        verbose_name_plural = _("Validation results")
        indexes = [
            models.Index(
                fields=[
                    "subject",
                ]
            ),
            models.Index(
                fields=[
                    "status",
                ]
            ),
        ]

    def save(self):
        self.message = self.message and self.message[:500]
        return super().save()

    @classmethod
    def create(cls, subject=None, status=None, message=None, data=None, creator=None):
        val_res = cls()
        val_res.subject = subject
        val_res.status = status
        val_res.message = message
        val_res.data = data
        val_res.creator = creator
        val_res.save()
        return val_res

    def update(self, status=None, message=None, data=None, updated_by=None):
        self.status = status
        self.message = message
        self.data = data
        self.updated_by = updated_by
        self.save()

    @property
    def row(self):
        # subject = group
        # message = advice
        try:
            s = json.dumps(self.data)
            data = self.data
        except Exception as e:
            data = str(self.data)
        return dict(
            subject=self.subject,
            status=self.status,
            message=self.message,
            data=data,
        )

    @classmethod
    def get_numbers(cls, package, report=None):
        params = {}
        if report:
            params["report"] = report
        else:
            params["report__package"] = package

        items = _get_numbers()
        for item in (
            cls.objects.filter(**params).values("status").annotate(total=Count("id"))
        ):
            items["total_" + item["status"].lower()] = item["total"]
        items["total"] = sum(items.values())
        logging.info(f"BaseValidationResult.get_numbers : {items}")
        return items

    @classmethod
    def rows(cls, package, fieldnames):
        for item in cls.objects.filter(report__package=package).iterator():
            data = {}
            data.update(item.row)
            data["package"] = package.package_name
            data["report"] = item.report.title
            yield {k: data.get(k) or "" for k in fieldnames}


class BaseXMLValidationResult(BaseValidationResult):
    # BaseValidationResult.status = response (ok -> success, 'error' -> failure)
    # BaseValidationResult.subject = item do resultado de validação do packtools
    # BaseValidationResult.message = message
    # BaseValidationResult.data = data

    # attribute = sub_item do resultado de validação do packtools
    # '@content-type="https://credit.niso.org/contributor-roles/*'
    attribute = models.CharField(
        _("Sub-item being analyzed"), null=True, blank=True, max_length=64
    )
    # focus = title do resultado de validação do packtools
    focus = models.CharField(_("Focus on"), null=True, blank=True, max_length=128)
    # validation_type = packtools validation_type
    validation_type = models.CharField(
        _("Validation type"),
        max_length=16,
        null=False,
        blank=False,
    )
    # geralemente article / sub-article e id
    parent = models.CharField(
        "article / sub-article", null=True, blank=True, max_length=11
    )
    parent_id = models.CharField("@id", null=True, blank=True, max_length=13)
    parent_article_type = models.CharField(
        "@article-type", null=True, blank=True, max_length=32
    )

    panels = [
        FieldPanel("subject", read_only=True),
        # FieldPanel("attribute", read_only=True),
        # FieldPanel("focus", read_only=True),
        # FieldPanel("parent", read_only=True),
        # FieldPanel("parent_id", read_only=True),
        # FieldPanel("parent_article_type", read_only=True),
        FieldPanel("message", read_only=True),
        FieldPanel("data", read_only=True),
    ]

    # def __str__(self):
    #     return str(self.row)

    class Meta:
        verbose_name = _("XML validation result")
        verbose_name_plural = _("XML validation results")

        indexes = [
            models.Index(
                fields=[
                    "attribute",
                ]
            ),
            models.Index(
                fields=[
                    "validation_type",
                ]
            ),
            models.Index(
                fields=[
                    "focus",
                ]
            ),
        ]


class XMLInfo(BaseXMLValidationResult):
    report = ParentalKey(
        "XMLInfoReport",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="xml_info",
    )

    class Meta:
        verbose_name = _("XML info")
        verbose_name_plural = _("XML infos")

    panels = BaseXMLValidationResult.panels


class XMLError(BaseXMLValidationResult, ClusterableModel):
    report = ParentalKey(
        "XMLErrorReport",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="xml_error",
    )
    expected_value = models.JSONField(
        _("Expected value"),
        null=True,
        blank=True,
    )
    got_value = models.JSONField(_("Got value"), null=True, blank=True)
    advice = models.CharField(_("Advice"), null=True, blank=True, max_length=500)
    reaction = models.CharField(
        _("Reaction"),
        max_length=16,
        choices=choices.ERROR_REACTION,
        default=choices.ER_REACTION_FIX,
        null=True,
        blank=True,
    )
    qa_decision = models.CharField(
        _("Decision"),
        max_length=32,
        choices=choices.ERROR_DECISION,
        null=True,
        blank=True,
    )

    panels = [
        FieldPanel("status", read_only=True),
        FieldPanel("advice", read_only=True),
        FieldPanel("data", read_only=True),
        FieldPanel("reaction"),
    ]

    class Meta:
        verbose_name = _("XML error")
        verbose_name_plural = _("XML errors")
        indexes = [
            models.Index(
                fields=[
                    "reaction",
                ]
            ),
            models.Index(
                fields=[
                    "qa_decision",
                ]
            ),
        ]

    def save(self):
        self.advice = self.advice and self.advice[:500]
        return super().save()

    @classmethod
    def get_numbers(cls, package, report=None):
        # ER_REACTION_FIX = "to-fix"
        # ER_REACTION_NOT_TO_FIX = "not-to-fix"
        # ER_REACTION_IMPOSSIBLE_TO_FIX = "unable-to-fix"

        # FIXME
        params = {}
        if report:
            params["report"] = report
        else:
            params["report__package"] = package

        total = 0
        items = _get_numbers()
        items.update({"total_to-fix": 0, "total_not-to-fix": 0, "total_unable-to-fix": 0})
        for item in (
            cls.objects.filter(**params).values("status", "reaction").annotate(total=Count("id"))
        ):
            items["total_" + item["status"].lower()] += item["total"]
            items["total_" + item["reaction"]] += item["total"]
            total += item["total"]

        items["total"] = total
        logging.info(f"XMLError.get_numbers : {items}")
        return items

class BaseValidationReport(CommonControlField):
    title = models.CharField(_("Title"), null=True, blank=True, max_length=128)
    category = models.CharField(
        _("Validation category"),
        max_length=32,
        choices=choices.VALIDATION_CATEGORY,
        null=False,
        blank=False,
    )
    creation = models.CharField(
        _("creation"),
        max_length=16,
        choices=choices.REPORT_CREATION,
        default=choices.REPORT_CREATION_NONE,
        null=False,
        blank=False,
    )
    ValidationResultClass = BaseValidationResult
    base_form_class = ValidationResultForm

    panels = [
        AutocompletePanel("package", read_only=True),
        FieldPanel("title", read_only=True),
    ]

    def __str__(self):
        return f"{self.package} {self.title}"

    class Meta:
        abstract = True
        verbose_name = _("Validation Report")
        verbose_name_plural = _("Validation Reports")
        unique_together = [
            (
                "package",
                "title",
                "category",
            )
        ]
        indexes = [
            models.Index(
                fields=[
                    "title",
                ]
            ),
            models.Index(
                fields=[
                    "creation",
                ]
            ),
            models.Index(
                fields=[
                    "category",
                ]
            ),
        ]

    @classmethod
    def get(cls, package=None, title=None, category=None):
        return cls.objects.get(package=package, title=title, category=category)

    @classmethod
    def create(cls, user, package=None, title=None, category=None):
        try:
            obj = cls()
            obj.creator = user
            obj.package = package
            obj.title = title
            obj.category = category
            obj.creation = choices.REPORT_CREATION_WIP
            obj.save()
            return obj
        except IntegrityError:
            logging.info({"package": package, "title": title, "category": category})
            return cls.get(package, title, category)

    @classmethod
    def create_or_update(cls, user, package, title, category, reset_validations):
        try:
            obj = cls.get(package, title, category)
            if reset_validations:
                cls.ValidationResultClass.objects.filter(
                    report__package=package
                ).delete()
            return obj
        except cls.DoesNotExist:
            return cls.create(user, package, title, category)

    def add_validation_result(
        self,
        status=None,
        message=None,
        data=None,
        subject=None,
    ):
        validation_result = self.ValidationResultClass.create(
            subject=subject or data and data.get("subject"),
            status=status,
            message=message,
            data=data,
            creator=self.creator,
        )
        validation_result.report = self
        validation_result.save()
        return validation_result

    @property
    def data(self):
        data = {
            "updated": self.updated and self.updated.isoformat()[:16].replace("T", " "),
            "creation": self.creation,
            "id": self.id,
            "category": self.category,
            "title": self.title,
        }
        data.update(self.get_numbers())
        logging.info(data)
        return data

    def finish_validations(self):
        self.creation = choices.REPORT_CREATION_DONE
        self.save()

    def get_numbers(self):
        items = _get_numbers()
        for item in (
            self.validation_results.all().values("status").annotate(total=Count("id"))
        ):
            items["total_" + item["status"].lower()] = item["total"]
        items["total"] = sum(items.values())
        logging.info(f"BaseValidationReport.get_numbers: {items}")
        return items


class PkgValidationResult(BaseValidationResult):
    report = ParentalKey(
        "ValidationReport",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="pkg_validation_result",
    )


class ValidationReport(BaseValidationReport, ClusterableModel):
    package = ParentalKey(
        Package,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="validation_report",
    )

    panels = BaseValidationReport.panels + [
        InlinePanel("pkg_validation_result", label=_("Result"))
    ]

    ValidationResultClass = PkgValidationResult

    @property
    def validation_results(self):
        return self.pkg_validation_result


class XMLInfoReport(BaseValidationReport, ClusterableModel):
    package = ParentalKey(
        Package,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="xml_info_report",
    )
    file = models.FileField(
        _("Report File"), upload_to=upload_package_directory_path, null=True, blank=True
    )
    panels = BaseValidationReport.panels + [FieldPanel("file")]

    ValidationResultClass = XMLInfo

    @property
    def validation_results(self):
        return self.xml_info

    def save_file(self, filename, content):
        try:
            self.file.delete(save=True)
        except Exception as e:
            pass
        self.file.save(filename, ContentFile(content))

    def generate_report(self):
        item = self.validation_results.first()

        if not item:
            return

        fieldnames = ["package"]
        fieldnames.extend(XMLInfo.cols)

        filename = self.package.name + f"-{report_datetime()}-xml_info.csv"
        with TemporaryDirectory() as targetdir:
            target = os.path.join(targetdir, filename)

            with open(target, "w", newline="") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for row in self.ValidationResultClass.rows(self.package, fieldnames):
                    writer.writerow(row)

            # saved optimised
            with open(target, "rb") as fp:
                self.save_file(filename, fp.read())

    def finish_validations(self):
        self.generate_report()
        self.creation = choices.REPORT_CREATION_DONE
        self.save()


class XMLErrorReport(BaseValidationReport, ClusterableModel):
    package = ParentalKey(
        Package,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="xml_error_report",
    )
    xml_producer_ack = models.BooleanField(
        _("The error review is complete"),
        blank=True,
        null=True,
        default=False,
    )

    panels = (
        []
        + BaseValidationReport.panels
        + [
            # FieldPanel("package"),
            InlinePanel("xml_error", label=_("XML error")),
            FieldPanel("xml_producer_ack"),
        ]
    )

    base_form_class = XMLErrorReportForm
    ValidationResultClass = XMLError

    class Meta:
        verbose_name = _("XML Error Report")
        verbose_name_plural = _("XML Error Reports")
        indexes = [
            models.Index(
                fields=[
                    "xml_producer_ack",
                ]
            ),
        ]

    @property
    def validation_results(self):
        return self.xml_error

    @property
    def data(self):
        d = super().data
        d["xml_producer_ack"] = self.xml_producer_ack
        d.update(self.get_numbers())
        return d

    def get_numbers(self):

        numbers = super().get_numbers()

        items = {}
        for item in (
            self.validation_results.all().values("reaction").annotate(total=Count("id"))
        ):
            items[item["reaction"]] = item["total"]
        # TODO
        # for item in self.validation_results.all().values("status", "reaction").annotate(total=Count("id")):
        #     items[(item["status"], item["reaction"])] = item["total"]

        numbers.update(
            {
                "reaction_to_fix": items.get(choices.ER_REACTION_FIX) or 0,
                "reaction_impossible_to_fix": items.get(
                    choices.ER_REACTION_IMPOSSIBLE_TO_FIX
                )
                or 0,
                "reaction_not_to_fix": items.get(choices.ER_REACTION_NOT_TO_FIX) or 0,
            }
        )
        logging.info(f"XMLErrorReport.get_numbers: {numbers}")
        return numbers


class UploadValidator(CommonControlField):
    collection = models.ForeignKey(
        Collection, null=True, blank=True, on_delete=models.SET_NULL
    )
    max_xml_warnings_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=100.00, help_text=_("0 to 100")
    )
    max_xml_errors_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=50.00, help_text=_("0 to 100")
    )
    max_impossible_to_fix_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=50.00, help_text=_("0 to 100")
    )
    decision_for_critical_errors = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        choices=choices.CRITICAL_ERROR_DECISION,
        default=choices.PS_VALIDATED_WITH_ERRORS,
    )
    publication_rule = models.CharField(
        max_length=16,
        null=True,
        blank=True,
        choices=choices.PUBLICATION_RULE,
        default=choices.FLEXIBLE_AUTO_PUBLICATION,
    )
    validation_params = models.JSONField(null=True, blank=True)

    panels = [
        FieldPanel("max_xml_warnings_percentage"),
        FieldPanel("max_xml_errors_percentage"),
        FieldPanel("max_impossible_to_fix_percentage"),
        FieldPanel("decision_for_critical_errors"),
        FieldPanel("publication_rule"),
        FieldPanel("validation_params")
    ]
    base_form_class = UploadValidatorForm

    # def __str__(self):
    #     if self.collection:
    #         return f"{self.collection.name}"
    #     return _("Validation rules")

    @classmethod
    def get(cls, collection):
        try:
            return UploadValidator.objects.get(collection=collection)
        except UploadValidator.DoesNotExist:
            return UploadValidator.create_default()

    @classmethod
    def create_default(cls):
        obj = UploadValidator(creator_id=1, collection=None)
        obj.save()
        return obj

    @staticmethod
    def get_publication_rule(collection=None):
        obj = UploadValidator.get(collection)
        return obj.publication_rule

    @staticmethod
    def calculate_publication_date(qa_publication_date, collection=None):
        obj = UploadValidator.get(collection)
        return obj.get_publication_date(qa_publication_date)

    def check_xml_errors_percentage(self, value):
        return self.validate_number(value, self.max_xml_errors_percentage)

    def check_xml_warnings_percentage(self, value):
        return self.validate_number(value, self.max_xml_warnings_percentage)

    def check_impossible_to_fix_percentage(self, value):
        return self.validate_number(value, self.max_impossible_to_fix_percentage)

    def validate_number(self, value, max_value):
        if not value:
            return True
        if self.rule == choices.STRICT_AUTO_PUBLICATION:
            return False
        # if self.rule == choices.MANUAL_PUBLICATION:
        #     return True
        return value <= max_value

    def is_acceptable_package(self, package):
        """
        Determina se o pacote é aceitável com base em vários critérios.

        Retorna:
            bool: True se o pacote for aceitável, False caso contrário.

        O pacote é considerado aceitável se:
        - Não houver erros bloqueadores.
        - O total de problemas for zero.
        - As porcentagens de erros e avisos XML estiverem dentro dos limites aceitáveis.
        - As porcentagens de erros XML contestados e declarados impossíveis de corrigir estiverem dentro dos limites aceitáveis.
        """
        if not package.is_validation_finished:
            return False

        logging.info(
            f"UploadValidator.is_acceptable_package - review finished: {package.is_error_review_finished}"
        )
        if package.is_error_review_finished:
            # avalia os números de erros, deduzindo os falsos positivos
            if not self.check_impossible_to_fix_percentage(package.declared_impossible_to_fix_percentage):
                return False
            if not self.check_xml_errors_percentage(package.xml_errors_percentage):
                return False
            return True

        if not self.check_xml_errors_percentage(package.xml_errors_percentage):
            return False
        if not self.check_xml_warnings_percentage(package.xml_warnings_percentage):
            return False
        return True

    def get_pos_validation_status(self, package, blocking_error_status=None):
        metrics = package.metrics
        logging.info(f"UploadValidator.get_pos_validation_status - {metrics}")

        total_validations = metrics["total_validations"]
        if not total_validations:
            # zero validações: problema inesperado
            return choices.PS_ENQUEUED_FOR_VALIDATION

        # verifica status a partir destes números
        if metrics["total_blocking"]:
            # pacote tem erros indiscutíveis
            # choices.PS_PENDING_CORRECTION | choices.PS_UNEXPECTED
            return blocking_error_status or choices.PS_PENDING_CORRECTION

        if metrics["total_xml_issues"] + metrics["total_pkg_issues"] == 0:
            # pacote sem erros identificados no XML, pode seguir
            return choices.PS_READY_TO_PREVIEW

        logging.info(f"UploadValidator.get_pos_validation_status: {self.publication_rule}")
        # algum erro identificado
        if self.rule == choices.STRICT_AUTO_PUBLICATION:
            # não importa o nível de criticidade, solicita correção
            return choices.PS_PENDING_CORRECTION

        if package.metrics["critical_errors"]:
            # solicita correção ou revisão dos problemas
            # PS_PENDING_CORRECTION or PS_VALIDATED_WITH_ERRORS
            return self.decision_for_critical_errors

        if self.rule == choices.FLEXIBLE_AUTO_PUBLICATION:
            if self.is_acceptable_package(package):
                # pacote com erros tolerados, pode seguir
                return choices.PS_READY_TO_PREVIEW

        if self.rule == choices.MANUAL_PUBLICATION:
            return choices.PS_VALIDATED_WITH_ERRORS

        # solicita revisão dos problemas
        return choices.PS_VALIDATED_WITH_ERRORS


class ArchivedPackage(Package):

    class Meta:
        proxy = True
