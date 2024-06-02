import csv
import logging
import os
from datetime import date, datetime, timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import IntegrityError, models
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtailautocomplete.edit_handlers import AutocompletePanel

from core.models import CommonControlField
from team.models import CollectionTeamMember
from upload import choices
from upload.forms import (
    QAPackageForm,
    UploadPackageForm,
    ValidationResultForm,
    XMLErrorReportForm,
)
from upload.permission_helper import ACCESS_ALL_PACKAGES, ASSIGN_PACKAGE, FINISH_DEPOSIT
from upload.utils import file_utils

User = get_user_model()


def now():
    return (
        datetime.utcnow().isoformat().replace(":", "").replace(" ", "").replace(".", "")
    )


def upload_package_directory_path(instance, filename):
    name, ext = os.path.splitext(filename)
    try:
        sps_pkg_name = instance.name
    except AttributeError:
        sps_pkg_name = instance.package.name

    subdirs = (sps_pkg_name or name).split("-")
    subdir_sps_pkg_name = "/".join(subdirs)

    return f"upload/{subdir_sps_pkg_name}/{ext[1:]}/{filename}"


class Package(CommonControlField, ClusterableModel):
    file = models.FileField(
        _("Package File"),
        upload_to=upload_package_directory_path,
        null=False,
        blank=False,
    )
    name = models.CharField(_("SPS Package name"), max_length=32, null=True, blank=True)
    signature = models.CharField(_("Signature"), max_length=32, null=True, blank=True)
    category = models.CharField(
        _("Category"),
        max_length=32,
        choices=choices.PACKAGE_CATEGORY,
        null=False,
        blank=False,
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
    )
    analyst = models.ForeignKey(
        CollectionTeamMember, blank=True, null=True, on_delete=models.SET_NULL
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

    validations = models.PositiveIntegerField(default=0)
    warnings = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)
    blocking_errors = models.PositiveIntegerField(default=0)

    absent_data_percentage = models.FloatField(default=0)
    error_percentage = models.FloatField(default=0)
    xml_errors_declared_to_fix_percentage = models.FloatField(default=0)
    xml_errors_declared_not_to_fix_percentage = models.FloatField(default=0)
    xml_errors_declared_absent_data_percentage = models.FloatField(default=0)

    xml_errors = 0
    xml_errors_to_fix = 0
    xml_errors_not_to_fix = 0
    xml_errors_absent_data = 0
    is_error_review_finished = 0

    panels = [
        FieldPanel("file"),
    ]

    base_form_class = UploadPackageForm

    class Meta:
        permissions = (
            (FINISH_DEPOSIT, _("Can finish deposit")),
            (ACCESS_ALL_PACKAGES, _("Can access all packages from all users")),
            (ASSIGN_PACKAGE, _("Can assign package")),
        )
        indexes = [
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
                    "validations",
                ]
            ),
            models.Index(
                fields=[
                    "expiration_date",
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
                    "blocking_errors",
                ]
            ),
            models.Index(
                fields=[
                    "errors",
                ]
            ),
            models.Index(
                fields=[
                    "warnings",
                ]
            ),
            models.Index(
                fields=[
                    "error_percentage",
                ]
            ),
            models.Index(
                fields=[
                    "absent_data_percentage",
                ]
            ),
            models.Index(
                fields=[
                    "xml_errors_declared_to_fix_percentage",
                ]
            ),
            models.Index(
                fields=[
                    "xml_errors_declared_not_to_fix_percentage",
                ]
            ),
            models.Index(
                fields=[
                    "xml_errors_declared_absent_data_percentage",
                ]
            ),
        ]

    autocomplete_search_field = "file"

    def autocomplete_label(self):
        return f"{self.package_name} - {self.category} - {self.article or self.issue} ({self.status})"

    def __str__(self):
        return self.package_name

    def save(self, *args, **kwargs):
        self.expiration_date = date.today() + timedelta(days=30)
        super(Package, self).save(*args, **kwargs)

    def files_list(self):
        files = {"files": []}

        try:
            files.update({"files": file_utils.get_file_list_from_zip(self.file.path)})
        except file_utils.BadPackageFileError:
            # É preciso capturar esta exceção para garantir que aqueles que
            #  usam files_list obtenham, na pior das hipóteses, um dicionário do tipo {'files': []}.
            # Isto pode ocorrer quando o zip for inválido, por exemplo.
            ...

        return files

    @property
    def package_name(self):
        name, ext = os.path.splitext(os.path.basename(self.name or self.file.name))
        return name

    @classmethod
    def get(cls, pkg_id=None, article=None):
        if pkg_id:
            return cls.objects.get(pk=pkg_id)
        if article:
            return cls.objects.get(article=article)

    @classmethod
    def create(cls, user_id, file, article_id=None, category=None, status=None):
        obj = cls()
        obj.article_id = article_id
        obj.creator_id = user_id
        obj.created = datetime.utcnow()
        obj.file = file
        obj.category = category or choices.PC_SYSTEM_GENERATED
        obj.status = status or choices.PS_PUBLISHED
        obj.save()
        return obj

    @classmethod
    def create_or_update(cls, user_id, file, article=None, category=None, status=None):
        try:
            obj = cls.get(article=article)
            obj.article = article
            obj.file = file
            obj.category = category
            obj.status = status
            obj.save()
            return obj
        except cls.DoesNotExist:
            return cls.create(
                user_id, file, article_id=article.id, category=category, status=status
            )

    @property
    def data(self):
        return dict(
            file=self.file.name,
            status=self.status,
            category=self.category,
            journal=self.journal and self.journal.data,
            issue=self.issue and self.issue.data,
            article=self.article and self.article.data,
            assignee=str(self.assignee),
            expiration_date=str(self.expiration_date),
        )

    @property
    def reports(self):
        for report in self.validation_report.all():
            yield report.data

    @property
    def xml_info_reports(self):
        for report in self.xml_info_report.all():
            yield report.data

    @property
    def xml_error_reports(self):
        for report in self.xml_error_report.all():
            yield report.data

    @property
    def is_validation_finished(self):
        if self.xml_info_report.filter(creation=choices.REPORT_CREATION_WIP).exists():
            return False
        if self.xml_error_report.filter(creation=choices.REPORT_CREATION_WIP).exists():
            return False
        if self.validation_report.filter(creation=choices.REPORT_CREATION_WIP).exists():
            return False
        return True

    def finish_validations(self):
        """
        Verifica a conclusão de todos os relatórios
        Contabiliza os totais de validações, erros, alertas, erros bloqueantes
        Modifica o status do pacote
        """
        if not self.is_validation_finished:
            return

        # contabiliza errors, warnings, blocking errors, etc
        self.validations = 0
        self.errors = 0
        self.warnings = 0
        self.blocking_errors = 0

        for report in self.validation_report.all():
            self.validations += report.validations
            self.errors += report.errors
            self.blocking_errors += report.blocking_errors
        for report in self.xml_info_report.all():
            self.validations += report.validations

        xml_errors = XMLError.objects.filter(report__package=self)
        count = xml_errors.count()
        self.validations += count
        self.errors += count
        self.warnings += xml_errors.filter(
            status=choices.VALIDATION_RESULT_WARNING
        ).count()
        absent_data = xml_errors.filter(
            Q(validation_type="exist") | Q(got_value__isnull=True)
        ).count()

        # verifica status a partir destes números
        if self.blocking_errors:
            self.status = choices.PS_REJECTED
        elif self.errors or self.warnings:
            self.status = choices.PS_VALIDATED_WITH_ERRORS
        elif (
            self.validations
            and (self.errors + self.warnings + self.blocking_errors) == 0
        ):
            self.status = choices.PS_APPROVED
        elif not self.validations:
            self.status = choices.PS_ENQUEUED_FOR_VALIDATION

        self.error_percentage = round(
            (self.errors + self.warnings) * 100 / self.validations, 2
        )
        self.absent_data_percentage = round(absent_data * 100 / self.validations, 2)
        self.save()

    @property
    def xml_producer_is_allowed_to_finish_deposit(self):
        # compara a porcentagem de erros que o produtor de XML declarou que não corrigirá
        # com a porcentagem máxima aceita de erros
        # compara a porcentagem de ausência de dados
        # que o produtor de XML declarou a ocorrência
        # com a porcentagem máxima aceita de dados faltantes
        return (
            self.errors == 0
            and self.xml_errors_declared_not_to_fix_percentage
            <= self.journal.max_error_percentage_accepted
            and self.absent_data_percentage
            <= self.journal.max_absent_data_percentage_accepted
        )

    def generate_error_report_content(self):
        first = XMLError.objects.filter(report__package=self).first()

        if not first:
            return

        with TemporaryDirectory() as targetdir:
            target = os.path.join(targetdir, self.package_name + "_xml_errors.csv")

            with open(target, "w", newline="") as csvfile:
                fieldnames = list(first.data.keys())
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for report in self.xml_error_reports.all():
                    for item in report.xml_error.all():
                        writer.writerow(item.data)

            # saved optimised
            with open(target, "rb") as fp:
                content = fp.read()

        return content

    def calculate_xml_error_declaration_numbers(self):
        items = (
            XMLError.objects.filter(report__package=self)
            .values(
                "reaction",
            )
            .annotate(count=Count("reaction"))
        )

        items = {item["reaction"]: item["count"] for item in items}
        total = sum(items.values())

        self.xml_errors = XMLError.objects.filter(report__package=self).count()
        self.xml_errors_to_fix = items[choices.ER_REACTION_FIX]
        self.xml_errors_declared_to_fix_percentage = round(
            items[choices.ER_REACTION_FIX] * 100 / total, 2
        )
        self.xml_errors_not_to_fix = items[choices.ER_REACTION_NOT_TO_FIX]
        self.xml_errors_declared_not_to_fix_percentage = round(
            items[choices.ER_REACTION_NOT_TO_FIX] * 100 / total, 2
        )
        self.xml_errors_absent_data = items[choices.ER_REACTION_ABSENT_DATA]
        self.xml_errors_declared_absent_data_percentage = round(
            items[choices.ER_REACTION_ABSENT_DATA] * 100 / total, 2
        )
        self.save()

    @property
    def summary(self):
        return {
            "is_validation_finished": self.is_validation_finished,
            "validations": self.validations,
            "warnings": self.warnings,
            "errors": self.errors,
            "blocking_errors": self.blocking_errors,
            "xml_errors": self.xml_errors,
            "xml_errors_to_fix": self.xml_errors_to_fix,
            # "xml_errors_not_to_fix": self.xml_errors_not_to_fix,
            # "xml_errors_absent_data": self.xml_errors_absent_data,
            "is_error_review_finished": self.is_error_review_finished,
            "xml_producer_is_allowed_to_finish_deposit": self.xml_producer_is_allowed_to_finish_deposit,
        }

    @property
    def is_error_review_finished(self):
        return not self.xml_error_report.filter(xml_producer_ack__isnull=False).exists()

    def finish_deposit(self):
        """
        Função para depositante (produtor de XML) que
        modifica o status do pacote de PS_VALIDATED_WITH_ERRORS para
        PS_PENDING_QA_DECISION ou PS_PENDING_CORRECTION
        """
        if self.xml_producer_is_allowed_to_finish_deposit:
            self.status = choices.PS_PENDING_QA_DECISION
        self.save()
        return True

    def get_errors_report_content(self):
        filename = self.name + f"-errors-to-fix-{now()}.csv"

        item = XMLError.objects.filter(report__package=self).first()
        item2 = PkgValidationResult.objects.filter(report__package=self).first()

        content = None
        fieldnames = (
            "subject",
            "attribute",
            "focus",
            "parent",
            "parent_id",
            "expected_value",
            "got_value",
            "message",
            "advice",
            "reaction",
        )
        default_data = {k: None for k in fieldnames}

        with TemporaryDirectory() as targetdir:
            target = os.path.join(targetdir, filename)

            with open(target, "w", newline="") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for item in PkgValidationResult.objects.filter(
                    report__package=self
                ).iterator():
                    data = dict(default_data)
                    data.update(item.info)
                    _data = {k: data[k] for k in fieldnames}
                    writer.writerow(_data)

                for item in XMLError.objects.filter(
                    report__package=self, reaction=choices.ER_REACTION_FIX
                ).iterator():
                    data = dict(default_data)
                    data.update(item.data)
                    _data = {k: data[k] for k in fieldnames}
                    writer.writerow(_data)

            # saved optimised
            with open(target, "rb") as fp:
                content = fp.read()

        return {"content": content, "filename": filename, "columns": fieldnames}


class QAPackage(Package):

    panels = [
        AutocompletePanel("analyst"),
        FieldPanel("qa_decision"),
    ]

    base_form_class = QAPackageForm

    class Meta:
        proxy = True


class BaseValidationResult(CommonControlField):

    subject = models.CharField(
        _("Subject"),
        null=True,
        blank=True,
        max_length=64,
        help_text=_("Item is being analyzed"),
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

    autocomplete_search_field = "subject"

    def autocomplete_label(self):
        return self.info

    def __str__(self):
        return "-".join(
            [
                self.subject,
                self.status,
            ]
        )

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
    def info(self):
        return dict(
            subject=self.subject,
            status=self.status,
            message=self.message,
            data=self.data,
        )


class BaseXMLValidationResult(BaseValidationResult):
    # BaseValidationResult.status = response (ok -> success, 'error' -> failure)
    # BaseValidationResult.subject = item do resultado de validação do packtools
    # BaseValidationResult.message = message
    # BaseValidationResult.data = data

    # attribute = sub_item do resultado de validação do packtools
    attribute = models.CharField(
        _("Subject Attribute"), null=True, blank=True, max_length=32
    )
    # geralemente article / sub-article e id
    parent = models.CharField(_("Parent"), null=True, blank=True, max_length=32)
    parent_id = models.CharField(_("Parent id"), null=True, blank=True, max_length=8)
    parent_article_type = models.CharField(
        _("Parent article type"), null=True, blank=True, max_length=32
    )

    # focus = title do resultado de validação do packtools
    focus = models.CharField(_("Analysis focus"), null=True, blank=True, max_length=64)
    # validation_type = packtools validation_type
    validation_type = models.CharField(
        _("Validation type"),
        max_length=16,
        null=False,
        blank=False,
    )

    panels = [
        FieldPanel("subject", read_only=True),
        FieldPanel("attribute", read_only=True),
        FieldPanel("focus", read_only=True),
        FieldPanel("parent", read_only=True),
        FieldPanel("parent_id", read_only=True),
        FieldPanel("data", read_only=True),
        FieldPanel("message", read_only=True),
    ]

    @property
    def info(self):
        return dict(
            status=self.status,
            subject=self.subject,
            attribute=self.attribute,
            focus=self.focus,
            parent=self.parent,
            parent_id=self.parent_id,
            data=self.data,
            message=self.message,
        )

    def __str__(self):
        return str(self.info)

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
            return cls.get(package, title, category)

    @classmethod
    def get_or_create(cls, user, package, title, category):
        try:
            return cls.get(package, title, category)
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
        return {
            "updated": self.updated.isoformat(),
            "creation": self.creation,
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "count": self.validations,
            "errors": self.errors,
            "blocking_errors": self.blocking_errors,
        }

    def finish_validations(self):
        self.creation = choices.REPORT_CREATION_DONE
        self.save()

    @property
    def validations(self):
        return self._validation_results.count()

    @property
    def errors(self):
        return self._validation_results.filter(
            status=choices.VALIDATION_RESULT_FAILURE
        ).count()

    @property
    def blocking_errors(self):
        if self.category in choices.ZERO_TOLERANCE:
            return self.errors
        else:
            return 0


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
    def _validation_results(self):
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
    def _validation_results(self):
        return self.xml_info

    def save_file(self, filename, content):
        try:
            self.file.delete(save=True)
        except Exception as e:
            pass
        self.file.save(filename, ContentFile(content))

    def generate_report(self):
        item = self._validation_results.first()

        if not item:
            return

        filename = self.package.name + "_xml_info_report.csv"
        with TemporaryDirectory() as targetdir:
            target = os.path.join(targetdir, filename)

            with open(target, "w", newline="") as csvfile:
                fieldnames = list(item.data.keys())
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for item in self._validation_results.all():
                    writer.writerow(item.data)

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
        _("The XML producer finished adding a response to each error."),
        blank=True,
        null=True,
        default=False,
    )

    panels = (
        []
        + BaseValidationReport.panels
        + [
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
    def warnings(self):
        return self.xml_error.filter(status=choices.VALIDATION_RESULT_WARNING).count()

    @property
    def errors(self):
        return self.xml_error.filter(status=choices.VALIDATION_RESULT_FAILURE).count()

    @property
    def reaction_to_fix(self):
        return self.xml_error.filter(
            reaction=choices.ER_REACTION_FIX,
        ).count()

    @property
    def reaction_not_to_fix(self):
        return self.xml_error.filter(
            reaction=choices.ER_REACTION_NOT_TO_FIX,
        ).count()

    @property
    def reaction_absent_data(self):
        return self.xml_error.filter(
            reaction=choices.ER_REACTION_ABSENT_DATA,
        ).count()

    @property
    def _validation_results(self):
        return self.xml_error

    @property
    def data(self):
        d = super().data
        d.update(
            {
                "reaction_to_fix": self.reaction_to_fix,
                "reaction_absent_data": self.reaction_absent_data,
                "reaction_not_to_fix": self.reaction_not_to_fix,
                "xml_producer_ack": self.xml_producer_ack,
            }
        )
        return d
