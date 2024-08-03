import csv
import logging
import os
from datetime import date, datetime, timedelta
from random import randint
from tempfile import TemporaryDirectory

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
from core.models import CommonControlField
from issue.models import Issue
from package import choices as package_choices
from package.models import SPSPkg
from proc.models import IssueProc, JournalProc, Operation
from team.models import CollectionTeamMember
from upload import choices
from upload.forms import (
    ApprovedPackageForm,
    QAPackageForm,
    UploadPackageForm,
    UploadValidatorForm,
    ValidationResultForm,
    XMLErrorReportForm,
)
from upload.permission_helper import ACCESS_ALL_PACKAGES, ASSIGN_PACKAGE, FINISH_DEPOSIT
from upload.utils import file_utils


class NotFinishedValitionsError(Exception):
    ...


User = get_user_model()


class UploadProcResult(Operation, Orderable):
    proc = ParentalKey("Package", related_name="upload_proc_result")


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
    )
    analyst = models.ForeignKey(
        CollectionTeamMember, blank=True, null=True, on_delete=models.SET_NULL
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

    blocking_errors = models.PositiveSmallIntegerField(default=0)
    xml_errors_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00
    )
    xml_warnings_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00
    )
    contested_xml_errors_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
    )
    declared_impossible_to_fix_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
    )

    order = models.PositiveSmallIntegerField(default=0)
    approved_date = models.DateField(null=True, blank=True)
    website_pub_date = models.DateField(null=True, blank=True)
    xml_pub_date = models.DateField(null=True, blank=True)
    pid_v2 = models.CharField(max_length=23, null=True, blank=True)

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
        ]

    autocomplete_search_field = "file"

    def autocomplete_label(self):
        return f"{self.package_name} - {self.category} - {self.article or self.issue} ({self.status})"

    def __str__(self):
        return self.package_name

    def save(self, *args, **kwargs):
        if not self.expiration_date:
            self.expiration_date = date.today() + timedelta(days=30)
        if self.status in (choices.PS_REJECTED, choices.PS_PENDING_CORRECTION):
            if self.article:
                self.article.update_status()
        if not self.qa_decision and self.status in (
            choices.PS_REJECTED,
            choices.PS_PENDING_CORRECTION,
            choices.PS_APPROVED,
            choices.PS_APPROVED_WITH_ERRORS,
        ):
            self.qa_decision = self.status

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
    def is_published(self):
        return bool(self.article)

    @property
    def package_name(self):
        if self.name:
            return self.name
        return self.file.name

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
        obj.category = category
        obj.status = status
        obj.qa_decision = None
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
        if PkgValidationResult.get_numbers(package=self).get("total_critical"):
            return True
        if self.xml_info_report.filter(creation=choices.REPORT_CREATION_WIP).exists():
            return False
        if self.xml_error_report.filter(creation=choices.REPORT_CREATION_WIP).exists():
            return False
        if self.validation_report.filter(creation=choices.REPORT_CREATION_WIP).exists():
            return False
        return True

    def finish_validations(self):
        """
        Finaliza as validações do pacote.

        Verifica se as validações já foram finalizadas e, em caso negativo,
        calcula os números de validação e atualiza o status do pacote
        de acordo com os resultados.

        Retorna:
            None

        O status do pacote é atualizado com base nas seguintes regras:
        - Se houver erros bloqueadores, o status será definido como 'PS_REJECTED'.
        - Se não houver nenhum problema, o status será definido como 'PS_APPROVED'.
        - Se houver problemas não bloqueadores, o status será definido como 'PS_VALIDATED_WITH_ERRORS'.
        """
        if not self.is_validation_finished:
            return

        self.calculate_validation_numbers()

        metrics = self.metrics
        total_validations = metrics["total_validations"]
        if not total_validations:
            self.status = choices.PS_ENQUEUED_FOR_VALIDATION
            self.save()
            return

        # verifica status a partir destes números
        if self.blocking_errors:
            # pacote tem erros indiscutíveis
            self.status = UploadValidator.get_decision_for_blocking_errors()
        elif metrics["total_validations"] == 0:
            self.status = choices.PS_APPROVED
        else:
            # pacote tem problemas que podem ser ou não erros
            # depende de uma decisão manual do produtor do XML e do analista
            self.status = choices.PS_VALIDATED_WITH_ERRORS
        self.save()

    def calculate_validation_numbers(self):
        # contabiliza errors, warnings, blocking errors, etc
        pkg_numbers = PkgValidationResult.get_numbers(package=self)
        xml_numbers = XMLError.get_numbers(package=self)

        total_xml_issues = xml_numbers["total"]
        total_pkg_issues = pkg_numbers["total"]
        total_validations = (
            XMLInfo.get_numbers(package=self).get("total")
            + total_xml_issues
            + total_pkg_issues
        )

        total_xml_errors = xml_numbers.get("total_errors") or 0
        total_xml_warnings = xml_numbers.get("total_warnings") or 0
        total_xml_blocking_errors = xml_numbers.get("total_critical") or 0

        total_pkg_blocking_errors = pkg_numbers["total_critical"]

        self.blocking_errors = total_xml_blocking_errors + total_pkg_blocking_errors
        self.xml_errors_percentage = round(
            total_xml_errors * 100 / total_validations, 2
        )
        self.xml_warnings_percentage = round(
            total_xml_warnings * 100 / total_validations, 2
        )

        self.numbers = {
            "total_validations": total_validations,
            "total_xml_errors": total_xml_errors,
            "total_xml_warnings": total_xml_warnings,
            "total_xml_issues": total_xml_errors
            + total_xml_warnings
            + total_xml_blocking_errors,
            "total_pkg_issues": total_pkg_issues,
        }
        self.save()

    @property
    def metrics(self):
        metrics = {
            "blocking_errors": self.blocking_errors,
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
        numbers = XMLError.get_numbers(package=self)
        total_xml_issues = numbers.get("total_xml_issues")

        total_contested_xml_errors = numbers.get("reaction_not_to_fix") or 0
        self.contested_xml_errors_percentage = round(
            total_contested_xml_errors * 100 / total_xml_issues, 2
        )

        total_declared_impossible_to_fix = (
            numbers.get("reaction_impossible_to_fix") or 0
        )
        self.declared_impossible_to_fix_percentage = round(
            total_declared_impossible_to_fix * 100 / total_xml_issues, 2
        )

        data = {
            "total_accepted_to_fix": numbers.get("reaction_to_fix") or 0,
            "total_contested_xml_errors": total_contested_xml_errors,
            "total_declared_impossible_to_fix": total_declared_impossible_to_fix,
        }
        if not self.numbers:
            self.numbers = {}
        self.numbers.update(data)
        self.save()

    def get_conclusion(self):
        if self.status == choices.PS_PENDING_QA_DECISION:
            return _("The XML producer has finished the errors review")

        if self.status == choices.PS_VALIDATED_WITH_ERRORS:
            return _("The XML producer is reviewing the errors")

        if (
            self.status == choices.PS_PENDING_CORRECTION
            or self.status == choices.PS_REJECTED
        ):
            return _("The XML producer must correct the package and submit again")

        metrics = self.metrics
        if self.status == choices.PS_PENDING_DEPOSIT:
            if self.is_error_review_finished:
                msgs = []
                if metrics["total_contested_xml_errors"]:
                    msgs.append(
                        _("The XML producer concluded that {} are not errors").format(
                            metrics["total_contested_xml_errors"]
                        )
                    )
                if metrics["total_declared_impossible_to_fix"]:
                    msgs.append(
                        _(
                            "The XML producer concluded that {} are impossible to fix"
                        ).format(metrics["total_declared_impossible_to_fix"])
                    )
                if not self.is_acceptable_package:
                    # <!-- User must finish the error review -->
                    msgs.append(
                        _("The XML producer must correct the package and submit again")
                    )

                else:
                    msgs.append(_("Finish the deposit"))
                return ". ".join(msgs)
            else:
                return _("Review and comment the errors")

    @property
    def is_error_review_finished(self):
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
        Finaliza o depósito do pacote.

        Avalia se o depósito do pacote pode ser finalizado com base em
        critérios específicos, como a existência de erros no XML,
        a conclusão da revisão de erros e a aceitabilidade do pacote.

        Retorna:
            bool: True se o depósito for finalizado com sucesso, False caso contrário.

        O depósito pode ser finalizado nas seguintes situações:
        - Se houver pelo menos um erro no XML que foi aceito na revisão de erros.
        - Se a revisão de erros foi concluída e o pacote é aceitável.

        Em caso contrário, o depósito não é finalizado e o status do pacote é
        atualizado para 'PS_PENDING_CORRECTION'.
        """
        if not self.status == choices.PS_VALIDATED_WITH_ERRORS:
            return False

        if not self.is_error_review_finished:
            # não pode finalizar, se não terminar a revisão ou ...
            return False

        metrics = self.metrics
        if metrics.get("reaction_to_fix"):
            # pode finalizar, se aceitar pelo menos 1 erro no XML ou ...
            self.status = choices.PS_PENDING_CORRECTION
            self.save()
            return True

        if self.is_acceptable_package:
            # pode finalizar, se a quantidade de erros é tolerável
            # para passar para uma avaliação manual
            self.status = choices.PS_PENDING_QA_DECISION
            self.save()
            return True

        # não pode finalizar, devido às correções pendentes
        self.status = choices.PS_PENDING_CORRECTION
        self.save()
        return False

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

        if self.blocking_errors:
            return False

        metrics = self.metrics

        if UploadValidator.check_max_xml_errors_percentage(
            self.xml_errors_percentage
        ) and UploadValidator.check_max_xml_warnings_percentage(
            self.xml_warnings_percentage
        ):
            # avalia os números sem a resposta da revisão de erros
            return True

        if self.is_error_review_finished:
            # avalia os números da resposta da revisão de erros
            return UploadValidator.check_max_xml_errors_percentage(
                self.contested_xml_errors_percentage
            ) and UploadValidator.check_max_impossible_to_fix_percentage(
                self.declared_impossible_to_fix_percentage
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

    def process_approved_package(self, user):
        logging.info(f"process_approved_package - status: {self.status}")

        save = False

        if self.is_allowed_to_change_publication_parameters:
            self.updated_by = user
            self.status = choices.PS_PREPARE_SPSPKG

            if not self.approved_date:
                self.approved_date = datetime.utcnow()

            if not self.order and self.article:
                # se package.order is None, regasta de article.order
                self.order = self.article.order

            if not self.website_pub_date:
                if self.article:
                    # se not package.website_pub_date, regasta de article.first_publication_date
                    self.website_pub_date = self.article.first_publication_date

            self.save()

        self.prepare_sps_package(user)
        self.prepare_article_publication(user)

    def update_xml_file(self, xml_with_pre):
        changed = False

        if not self.order:
            try:
                self.order = int(xml_with_pre.order or xml_with_pre.fpage)
            except (TypeError, ValueError):
                pass

        try:
            article_publication_date = xml_with_pre.article_publication_date
            article_publication_date = datetime.fromisoformat(article_publication_date)
        except Exception as e:
            article_publication_date = None

        if not self.website_pub_date:
            try:
                self.website_pub_date = article_publication_date
            except XMLWithPreArticlePublicationDateError as e:
                self.website_pub_date = UploadValidator.calculate_publication_date(
                    datetime.utcnow()
                )

        if self.website_pub_date != article_publication_date:
            # atualiza a data de publicação do artigo no site público
            xml_with_pre.article_publication_date = {
                "year": self.website_pub_date.year,
                "month": self.website_pub_date.month,
                "day": self.website_pub_date.day,
            }
            changed = True

        if changed:
            xml_with_pre.update_xml_in_zip_file()

        return changed

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
                self.update_xml_file(xml_with_pre)
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

    def start(self, user, name):
        # self.save()
        # operation = Operation.start(user, name)
        # self.operations.add(operation)
        # return operation
        return UploadProcResult.start(user, self, name)

    @property
    def is_approved(self):
        return self.status in (choices.PS_APPROVED, choices.PS_APPROVED_WITH_ERRORS)

    def update_sps_pkg_status(self):
        # conseguiu registrar no minio
        # TODO melhora a atribuição do status
        self.status = choices.PS_PREPARE_PUBLICATION
        self.save()

    def prepare_article_publication(self, user):
        logging.info(f"prepare_article_publication - status: {self.status}")
        self.article = Article.create_or_update(
            user, self.sps_pkg, self.issue, self.journal or self.issue.journal
        )
        self.article.set_position(self.order)
        self.order = self.article.order
        self.save()

    def update_status(self, new_status=None):
        self.status = new_status or choices.PS_PUBLISHED
        self.save()
        self.article.update_status()

    @property
    def is_allowed_to_change_publication_parameters(self):
        return self.status in (
            choices.PS_APPROVED,
            choices.PS_APPROVED_WITH_ERRORS,
            choices.PS_PREPARE_SPSPKG,
            choices.PS_PREPARE_PUBLICATION,
            choices.PS_READY_TO_QA_WEBSITE,
            choices.PS_READY_TO_PUBLISH,
            choices.PS_SCHEDULED_PUBLICATION,
            choices.PS_PUBLISHED,
        )

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


class QAPackage(Package):

    panels = [
        FieldPanel("status", read_only=True),
        AutocompletePanel("analyst"),
        FieldPanel("qa_decision"),
    ]

    base_form_class = QAPackageForm

    class Meta:
        proxy = True


class ApprovedPackage(Package):

    panels = [
        FieldPanel("status", read_only=True),
        AutocompletePanel("analyst", read_only=True),
        FieldPanel("qa_decision", read_only=True),
        FieldPanel("approved_date", read_only=True),
        FieldPanel("order"),
        FieldPanel("website_pub_date"),
        FieldPanel("pid_v2"),
    ]

    base_form_class = ApprovedPackageForm

    class Meta:
        proxy = True


class BaseValidationResult(CommonControlField):

    subject = models.CharField(
        _("Subject"),
        null=True,
        blank=True,
        max_length=64,
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

        items = {}
        for item in (
            cls.objects.filter(**params).values("status").annotate(total=Count("id"))
        ):
            items[item["status"]] = item["total"]

        return {
            "total": sum(items.values()),
            "total_critical": items.get(choices.VALIDATION_RESULT_CRITICAL) or 0,
            "total_errors": items.get(choices.VALIDATION_RESULT_FAILURE) or 0,
            "total_warnings": items.get(choices.VALIDATION_RESULT_WARNING) or 0,
        }

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
    focus = models.CharField(_("Focus on"), null=True, blank=True, max_length=64)
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
        return data

    def finish_validations(self):
        self.creation = choices.REPORT_CREATION_DONE
        self.save()

    def get_numbers(self):
        items = {}
        for item in (
            self.validation_results.all().values("status").annotate(total=Count("id"))
        ):
            items[item["status"]] = item["total"]

        return {
            "total": sum(items.values()),
            "total_critical": items.get(choices.VALIDATION_RESULT_CRITICAL) or 0,
            "total_errors": items.get(choices.VALIDATION_RESULT_FAILURE) or 0,
            "total_warnings": items.get(choices.VALIDATION_RESULT_WARNING) or 0,
        }


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
        _("The XML producer finished adding a response to each error."),
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
        return numbers


class UploadValidator(CommonControlField):
    collection = models.ForeignKey(
        Collection, null=True, blank=True, on_delete=models.SET_NULL
    )
    max_xml_warnings_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.1
    )
    max_xml_errors_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.1
    )
    max_impossible_to_fix_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.05
    )
    days_in_qa_before_publication = models.PositiveSmallIntegerField(
        default=0,
        help_text=_(
            "Enter the number of days for quality control before publishing. Articles are automatically visible after this time."
        ),
    )
    decision_for_blocking_errors = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        choices=choices.CRITICAL_ERROR_DECISION,
        default=choices.PS_VALIDATED_WITH_ERRORS,
    )

    panels = [
        FieldPanel("max_xml_warnings_percentage"),
        FieldPanel("max_xml_errors_percentage"),
        FieldPanel("max_impossible_to_fix_percentage"),
        FieldPanel("days_in_qa_before_publication"),
        FieldPanel("decision_for_blocking_errors"),
    ]
    base_form_class = UploadValidatorForm

    @classmethod
    def create_default(cls):
        obj = UploadValidator(creator_id=1, collection=None)
        obj.save()
        return obj

    @staticmethod
    def get_decision_for_blocking_errors(collection=None):
        try:
            obj = UploadValidator.objects.get(collection=collection)
        except UploadValidator.DoesNotExist:
            obj = UploadValidator.create_default()
        return obj.decision_for_blocking_errors

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
        return value <= obj.max_xml_errors_percentage

    @staticmethod
    def check_max_xml_warnings_percentage(value, collection=None):
        try:
            obj = UploadValidator.objects.get(collection=collection)
        except UploadValidator.DoesNotExist:
            obj = UploadValidator.create_default()
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

    def get_publication_date(self, qa_publication_date):
        #  - Create a timedelta object with the number of days
        if self.days_in_qa_before_publication:
            time_delta = timedelta(days=self.days_in_qa_before_publication)

            #  - Add the timedelta to the date object
            return qa_publication_date + time_delta
        return qa_publication_date
