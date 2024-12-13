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


class QADecisionException(Exception):
    pass


class NotFinishedValitionsError(Exception): ...


User = get_user_model()


class UploadProcResult(Operation, Orderable):
    proc = ParentalKey("Package", related_name="upload_proc_result")


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
        found = False
        with ZipFile(self.file.path) as zf:
            # obtém os components do zip
            file_paths = set(zf.namelist() or [])
            logging.info(f"file_paths: {file_paths}")

            other_files = {}
            xmls = {}
            for file_path in file_paths:
                basename = os.path.basename(file_path)
                if basename.startswith("."):
                    continue
                name, ext = os.path.splitext(basename)
                data = {"file_path": file_path, "basename": basename}
                logging.info(f"{self.file.path} {data}")

                if ext == ".xml":
                    xmls.setdefault(name, [])
                    xmls[name].append(data)
                else:
                    other_files.setdefault(name, [])
                    other_files[name].append(data)

            logging.info(f"xmls: {xmls}")
            logging.info(f"other_files: {other_files}")

            for key in xmls.keys():
                other_files_copy = other_files.copy()
                for other_files_key in other_files_copy.keys():
                    logging.info(f"xml: {key}, other_files_key: {other_files_key}")
                    if other_files_key.startswith(key + "."):
                        xmls[key].extend(other_files.pop(other_files_key))
                        logging.info(f"files ({key}): {xmls[key]}")
                    elif other_files_key.startswith(key + "-"):
                        xmls[key].extend(other_files.pop(other_files_key))
                        logging.info(f"files ({key}): {xmls[key]}")

            logging.info(xmls)
            for key, files in xmls.items():
                logging.info(f"{key} {files}")
                try:
                    with TemporaryDirectory() as tmpdirname:
                        zfile = os.path.join(tmpdirname, f"{key}.zip")
                        with ZipFile(zfile, "w", compression=ZIP_DEFLATED) as zfw:
                            for item in files:
                                zfw.writestr(
                                    item["basename"], zf.read(item["file_path"])
                                )

                        with open(zfile, "rb") as zfw:
                            content = zfw.read()

                    yield {
                        "xml_name": key,
                        "package": Package.create_or_update(
                            user, key, self, key + ".zip", content
                        ),
                    }
                except Exception as exc:
                    logging.exception(exc)
                    yield {"xml_name": key, "error": str(exc)}


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
            for item in XMLWithPre.create(path=self.file.path):
                return item.tostring(pretty_print=True)
        except Exception as e:
            return f"<root>invalid xml {e}</root>"

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
        for item in XMLWithPre.create(path=self.file.path):
            renditions = item.renditions

            with ZipFile(self.file.path) as zf:
                for rendition in renditions:
                    rendition["content"] = zf.read(rendition["name"])
                    yield rendition

    def files_list(self):
        try:
            for xml_with_pre in XMLWithPre.create(path=self.file.path):
                return {"files": xml_with_pre.files}
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

    def finish_validations(
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

        metrics = self.metrics
        total_validations = metrics["total_validations"]
        if not total_validations:
            # zero validações: problema inesperado
            self.status = choices.PS_ENQUEUED_FOR_VALIDATION
            self.save()
            return

        logging.info(f"Package.finish_validations - {metrics}")
        # verifica status a partir destes números
        if metrics["total_blocking"]:
            # pacote tem erros indiscutíveis
            # choices.PS_PENDING_CORRECTION | choices.PS_UNEXPECTED
            self.status = blocking_error_status or choices.PS_PENDING_CORRECTION
        elif (
            metrics["total_validations"] > 0
            and (metrics["total_xml_issues"] + metrics["total_pkg_issues"]) == 0
        ):
            # pacote sem erros identificados no XML, pode seguir
            self.status = choices.PS_READY_TO_PREVIEW
        else:
            rule = UploadValidator.get_publication_rule()
            logging.info(f"Package.finish_validations - rule: {rule}")
            if rule == choices.STRICT_AUTO_PUBLICATION:
                # não importa o nível de criticidade, solicita correção
                self.status = choices.PS_PENDING_CORRECTION

            elif rule == choices.MANUAL_PUBLICATION:
                # avalia o nível de criticidade, solicita correção ou revisão dos problemas
                if metrics["critical_errors"]:
                    # solicita correção ou revisão dos problemas
                    self.status = UploadValidator.get_decision_for_critical_errors()
                else:
                    # solicita revisão dos problemas
                    self.status = choices.PS_VALIDATED_WITH_ERRORS

            elif rule == choices.FLEXIBLE_AUTO_PUBLICATION:
                if self.is_acceptable_package:
                    # pacote com erros tolerados, pode seguir
                    self.status = choices.PS_READY_TO_PREVIEW
                else:
                    # solicita revisão dos problemas
                    self.status = choices.PS_VALIDATED_WITH_ERRORS

        logging.info(f"Package.finish_validations - status: {self.status}")

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

        self.save()

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

        self.critical_errors = pkg_numbers["total_critical"]

        self.xml_errors_percentage = round(
            xml_numbers["total_error"] * 100 / total_validations, 2
        )
        self.xml_warnings_percentage = round(
            xml_numbers["total_warning"] * 100 / total_validations, 2
        )

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

    def calculate_error_review_numbers(self):
        if not self.is_validation_finished:
            raise NotFinishedValitionsError(f"Validation is not finished: {self}")

        # TODO abater as validações com status=WARNING e reação IMPOSSIBLE_TO_FIX
        xml_numbers = XMLError.get_numbers(package=self)

        total_contested_xml_errors = xml_numbers.get("reaction_not_to_fix") or 0
        self.contested_xml_errors_percentage = round(
            total_contested_xml_errors * 100 / xml_numbers["total"], 2
        )

        total_declared_impossible_to_fix = (
            xml_numbers.get("reaction_impossible_to_fix") or 0
        )
        self.declared_impossible_to_fix_percentage = round(
            total_declared_impossible_to_fix * 100 / xml_numbers["total"], 2
        )

        data = {
            "total_accepted_to_fix": xml_numbers.get("reaction_to_fix") or 0,
            "total_contested_xml_errors": total_contested_xml_errors,
            "total_declared_impossible_to_fix": total_declared_impossible_to_fix,
        }
        if not self.numbers:
            self.numbers = {}
        self.numbers.update(data)
        self.save()
        logging.info(f"Package.calculate_error_review_numbers: {self.metrics}")

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
        if not self.is_validation_finished:
            return False

        metrics = self.metrics

        logging.info(
            f"Package.is_acceptable_package - review finished: {self.is_error_review_finished}"
        )
        if self.is_error_review_finished:
            # avalia os números de erros, deduzindo os falsos positivos
            return UploadValidator.check_max_xml_errors_percentage(
                self.contested_xml_errors_percentage
            ) and UploadValidator.check_max_impossible_to_fix_percentage(
                self.declared_impossible_to_fix_percentage
            )
        # avalia os números de erros, sem deduzir os falsos positivos
        return UploadValidator.check_max_xml_errors_percentage(
            self.xml_errors_percentage
        ) and UploadValidator.check_max_xml_warnings_percentage(
            self.xml_warnings_percentage
        )

    def get_errors_report_content(self):
        filename = self.name + f"-{report_datetime()}-errors.csv"

        item = XMLError.objects.filter(report__package=self).first()
        item2 = PkgValidationResult.objects.filter(report__package=self).first()

        content = None
        fieldnames = (
            "package",
            "group",
            "article / sub-article",
            "@id",
            "@article-type",
            "item",
            "sub-item",
            "validation type",
            "focus on",
            "status",
            "expected value",
            "got value",
            "message",
            "advice",
            "reaction",
            "data",
        )
        default_data = {k: None for k in fieldnames}

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
        operation = self.start(user, "process_qa_decision")

        if self.qa_decision == choices.PS_PENDING_QA_DECISION:
            self.finish_qa_decision(
                user, operation, websites=None, result=None, rule=None
            )
            return []

        if self.qa_decision == choices.PS_PENDING_CORRECTION:
            self.finish_qa_decision(
                user, operation, websites=None, result=None, rule=None
            )
            return []

        if self.qa_decision == choices.PS_DEPUBLISHED:
            # TODO
            operation.finish(
                user,
                completed=True,
                detail={"decision": self.qa_decision, "error": "not implemented"},
            )
            return []

        if self.qa_decision not in (
            choices.PS_READY_TO_PREVIEW,
            choices.PS_READY_TO_PUBLISH,
        ):
            operation.finish(
                user,
                completed=True,
                detail={"decision": self.qa_decision, "error": "unexpected decision"},
            )
            return []

        save = False
        user = user or self.updated_by or self.creator

        websites = []

        try:
            # gera pacote sps e o valida quanto a compontentes disponíveis no minio
            result = self.prepare_sps_package(user) or {}

            # verifica pela regra de publicação e pela situação do pacote
            # se pode ser publicado em PUBLIC
            rule = UploadValidator.get_publication_rule()

            self.analyze_result(user, result, websites, rule)
        except QADecisionException as exc:
            logging.exception(exc)
            result["exception"] = exc
            self.finish_qa_decision(user, operation, websites, result, rule)
            return websites

        # nenhum erro ou regra flexível, permissão de publicar no site público
        self.qa_decision = choices.PS_READY_TO_PUBLISH
        self.status = choices.PS_READY_TO_PUBLISH
        if (
            not self.linked
            or not self.linked.filter(~Q(status=choices.PS_READY_TO_PUBLISH)).exists()
        ):
            # nenhum pacote vinculado como outros ou
            # todos os pacotes vinculados estão com o mesmo status
            # (choices.PS_READY_TO_PUBLISH), então pode publicar em PUBLIC
            websites.append("PUBLIC")

        self.finish_qa_decision(user, operation, websites, result, rule)
        return websites

    def analyze_result(self, user, result, websites, rule):
        if result.get("blocking_errors"):
            # não foi possível criar sps package
            result["request_correction"] = True
            raise QADecisionException(_("Cannot publish article: blocking errors"))

        if self.qa_decision == choices.PS_READY_TO_PREVIEW:
            try:
                # cria ou atualiza Article
                self.create_or_update_article(user, save=False)
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                result["request_correction"] = True
                result.update(
                    {
                        "exception": {
                            "message": str(e),
                            "type": str(type(e)),
                            "traceback": str(traceback.format_tb(exc_traceback)),
                        }
                    }
                )
                raise QADecisionException(
                    _("Cannot publish article: unexpected errors")
                )
            # publica em QA não importa a gravidade dos erros
            websites.append("QA")

        if result.get("critical_errors"):
            # com erros críticos somente publica em QA
            result["request_correction"] = True
            raise QADecisionException(_("Cannot publish article: critical errors"))

        if rule == choices.STRICT_AUTO_PUBLICATION:
            if result.get("error") or self.has_errors:
                # Há erros e é modo rígido, somente publica em QA
                result["request_correction"] = True
                raise QADecisionException(
                    _(
                        "Article has errors. System settings (STRICT_AUTO_PUBLICATION) blocks its publication"
                    )
                )

        elif rule == choices.MANUAL_PUBLICATION:
            # No modo de publicação manual no website PUBLIC,
            # com ou sem erros, é decisão do analista
            if self.qa_decision == choices.PS_READY_TO_PREVIEW:
                # publica somente em QA
                result["request_correction"] = False
                raise QADecisionException(
                    _(
                        "It requires manual publication due to system settings (MANUAL_PUBLICATION)"
                    )
                )

    def finish_qa_decision(self, user, operation, websites, result, rule):
        try:
            exception = result.pop("exception")
        except (KeyError, AttributeError, TypeError, ValueError):
            exception = None

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

    def xml_file_changed(self, xml_with_pre, first_release_date):
        """
        Se aplicável, atualiza o XML com a data de publicação do artigo
        """
        changed = False
        try:
            article_publication_date = xml_with_pre.article_publication_date
            article_publication_date = datetime.fromisoformat(article_publication_date)
            a_date = (
                article_publication_date.year,
                article_publication_date.month,
                article_publication_date.day,
            )
        except Exception as e:
            a_date = None

        release_date = first_release_date or datetime.utcnow()
        r_date = (release_date.year, release_date.month, release_date.day)
        if a_date != r_date:
            # atualiza a data de publicação do artigo no site público
            xml_with_pre.article_publication_date = {
                "year": release_date.year,
                "month": release_date.month,
                "day": release_date.day,
            }
            changed = True

        if not xml_with_pre.v2:
            xml_with_pre.v2 = self.get_or_generate_pid_v2()
            changed = True

        if changed:
            # xml_with_pre.update_xml_in_zip_file()
            update_zip_file(self.file.path, xml_with_pre)
            return True

    def get_or_generate_pid_v2(self):
        issue_pid = IssueProc.get_or_generate_issue_pid(self.issue)
        # Nota: order não é o mesmo que pid
        number = str(self.order or randint(0, 100000)).zfill(5)
        return f"S{issue_pid}{number}"

    def prepare_sps_package(self, user):
        # Aplica-se também para um pacote de atualização de um conteúdo anteriormente migrado
        # TODO components, texts
        for xml_with_pre in XMLWithPre.create(path=self.file.path):
            if (
                self.xml_file_changed(
                    xml_with_pre, self.article and self.article.first_publication_date
                )
                or not self.sps_pkg
                or not self.sps_pkg.valid_components
            ):
                texts = {
                    "xml_langs": list(xml_with_pre.langs),
                    "pdf_langs": [
                        rendition["lang"]
                        for rendition in xml_with_pre.renditions
                        if rendition in xml_with_pre.filenames
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

        warnings = []
        errors = []
        critical_errors = []
        blocking_errors = []
        if self.sps_pkg:
            if not self.sps_pkg.registered_in_core:
                critical_errors.append(
                    _("SPS package must be registered in the Core system")
                )
            if not self.sps_pkg.valid_components:
                missing = ", ".join(
                    [
                        component.basename
                        for component in self.sps_pkg.components.filter(uri=None)
                    ]
                )
                errors.append(_("{} is/are not stored in the cloud").format())
            if not self.sps_pkg.valid_texts:
                warnings.append(_("Total of XML, PDF, HTML do not match"))
        else:
            blocking_errors.append(_("Unable to prepare the package to publish"))

        return {
            "blocking_errors": blocking_errors,
            "critical_errors": critical_errors,
            "errors": errors,
            "warnings": warnings,
        }

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
        logging.info(f"create_or_update_article - status: {self.status}")
        if not self.issue:
            ValueError("Unable to create or update article: missing issue")
        if not self.journal:
            ValueError("Unable to create or update article: missing journal")

        self.article = Article.create_or_update(
            user, self.sps_pkg, self.issue, self.journal, self.order
        )

        # atualizar package.order com article.order, cujo valor position or fpage
        self.order = self.article.position
        if save:
            self.save()

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


class QAPackage(Package):
    """
    XML validated with errors
    QA can approve or reject

    """

    panel_decision = [
        FieldPanel("status", read_only=True),
        FieldPanel("qa_decision"),
        FieldPanel("qa_comment"),
        AutocompletePanel("analyst"),
        FieldPanel("order"),
        AutocompletePanel("linked"),
    ]
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

    panel_data = [
        FieldPanel("status", read_only=True),
        AutocompletePanel("analyst", read_only=True),
        FieldPanel("qa_ws_status", read_only=True),
        FieldPanel("qa_ws_pubdate", read_only=True),
        FieldPanel("public_ws_status", read_only=True),
        FieldPanel("public_ws_pubdate", read_only=True),
        FieldPanel("qa_decision"),
        FieldPanel("qa_comment"),
        FieldPanel("order"),
        AutocompletePanel("linked"),
    ]

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
    message = models.TextField(_("Message"), null=True, blank=True)
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
        return dict(
            subject=self.subject,
            status=self.status,
            message=self.message,
            data=str(self.data),
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
        default_data = {k: None for k in fieldnames}

        for item in cls.objects.filter(report__package=package).iterator():
            data = dict(default_data)
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
        "article / sub-article", null=True, blank=True, max_length=16
    )
    parent_id = models.CharField("@id", null=True, blank=True, max_length=8)
    parent_article_type = models.CharField(
        "@article-type", null=True, blank=True, max_length=32
    )

    panels = [
        FieldPanel("subject", read_only=True),
        FieldPanel("attribute", read_only=True),
        FieldPanel("focus", read_only=True),
        FieldPanel("parent", read_only=True),
        FieldPanel("parent_id", read_only=True),
        FieldPanel("parent_article_type", read_only=True),
        FieldPanel("data", read_only=True),
        FieldPanel("message", read_only=True),
    ]

    @property
    def row(self):
        return {
            "status": self.status,
            "item": self.subject,
            "sub-item": self.attribute,
            "focus on": self.focus,
            "article / sub-article": self.parent,
            "@id": self.parent_id,
            "@article-type": self.parent_article_type,
            "message": self.message,
            "validation type": self.validation_type,
            "data": str(self.data),
        }

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
    advice = models.CharField(_("Advice"), null=True, blank=True, max_length=256)
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
        FieldPanel("subject", read_only=True),
        FieldPanel("attribute", read_only=True),
        FieldPanel("focus", read_only=True),
        FieldPanel("parent", read_only=True),
        FieldPanel("parent_id", read_only=True),
        FieldPanel("data", read_only=True),
        FieldPanel("expected_value", read_only=True),
        FieldPanel("got_value", read_only=True),
        FieldPanel("message", read_only=True),
        FieldPanel("advice", read_only=True),
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

    @property
    def row(self):
        data = {
            "status": self.status,
            "item": self.subject,
            "sub-item": self.attribute,
            "focus on": self.focus,
            "article / sub-article": self.parent,
            "@id": self.parent_id,
            "@article-type": self.parent_article_type,
            "expected value": self.expected_value,
            "got value": self.got_value,
            "message": self.message,
            "advice": self.advice,
            "reaction": self.reaction,
            "validation type": self.validation_type,
            "data": str(self.data),
        }
        return data


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

        fieldnames = (
            "package",
            "article / sub-article",
            "@id",
            "@article-type",
            "item",
            "sub-item",
            "validation type",
            "focus on",
            "message",
            "data",
        )

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

    panels = [
        FieldPanel("max_xml_warnings_percentage"),
        FieldPanel("max_xml_errors_percentage"),
        FieldPanel("max_impossible_to_fix_percentage"),
        FieldPanel("decision_for_critical_errors"),
        FieldPanel("publication_rule"),
    ]
    base_form_class = UploadValidatorForm

    # def __str__(self):
    #     if self.collection:
    #         return f"{self.collection.name}"
    #     return _("Validation rules")

    @classmethod
    def create_default(cls):
        obj = UploadValidator(creator_id=1, collection=None)
        obj.save()
        return obj

    @staticmethod
    def get_publication_rule(collection=None):
        try:
            obj = UploadValidator.objects.get(collection=collection)
        except UploadValidator.DoesNotExist:
            obj = UploadValidator.create_default()
        return obj.publication_rule

    @staticmethod
    def get_decision_for_critical_errors(collection=None):
        try:
            obj = UploadValidator.objects.get(collection=collection)
        except UploadValidator.DoesNotExist:
            obj = UploadValidator.create_default()
        return obj.decision_for_critical_errors

    @staticmethod
    def calculate_publication_date(qa_publication_date, collection=None):
        try:
            obj = UploadValidator.objects.get(collection=collection)
        except UploadValidator.DoesNotExist:
            obj = UploadValidator.create_default()
        return obj.get_publication_date(qa_publication_date)

    @staticmethod
    def check_max_xml_errors_percentage(value, collection=None):
        try:
            obj = UploadValidator.objects.get(collection=collection)
        except UploadValidator.DoesNotExist:
            obj = UploadValidator.create_default()
        logging.info(
            f"check_max_xml_errors_percentage: {value} <= {obj.max_xml_errors_percentage}"
        )
        return value <= obj.max_xml_errors_percentage

    @staticmethod
    def check_max_xml_warnings_percentage(value, collection=None):
        try:
            obj = UploadValidator.objects.get(collection=collection)
        except UploadValidator.DoesNotExist:
            obj = UploadValidator.create_default()
        logging.info(
            f"check_max_xml_warnings_percentage: {value} <= {obj.max_xml_warnings_percentage}"
        )
        return value <= obj.max_xml_warnings_percentage

    @staticmethod
    def check_max_impossible_to_fix_percentage(value, collection=None):
        try:
            obj = UploadValidator.objects.get(collection=collection)
        except UploadValidator.DoesNotExist:
            obj = UploadValidator.create_default()
        return value <= obj.max_impossible_to_fix_percentage

    def check_xml_errors_percentage(self, value):
        return value <= self.max_xml_errors_percentage

    def check_xml_warnings_percentage(self, value):
        return value <= self.max_xml_warnings_percentage

    def check_impossible_to_fix_percentage(self, value):
        return value <= self.max_impossible_to_fix_percentage


class ArchivedPackage(Package):

    class Meta:
        proxy = True
