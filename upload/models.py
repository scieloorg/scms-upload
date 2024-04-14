from datetime import date, timedelta, datetime

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, MultiFieldPanel, TabbedInterface, ObjectList
from wagtailautocomplete.edit_handlers import AutocompletePanel

from article.models import Article
from core.models import CommonControlField
from issue.models import Issue
from journal.models import Journal

from . import choices
from .forms import UploadPackageForm, ValidationResultForm
from .permission_helper import (
    ACCESS_ALL_PACKAGES,
    ANALYSE_VALIDATION_ERROR_RESOLUTION,
    ASSIGN_PACKAGE,
    FINISH_DEPOSIT,
    SEND_VALIDATION_ERROR_RESOLUTION,
)
from .utils import file_utils

User = get_user_model()


class Package(CommonControlField):
    file = models.FileField(_("Package File"), null=False, blank=False)
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
    article = models.ForeignKey(
        Article,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    journal = models.ForeignKey(Journal, blank=True, null=True, on_delete=models.SET_NULL)
    issue = models.ForeignKey(Issue, blank=True, null=True, on_delete=models.SET_NULL)
    assignee = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL)
    expiration_date = models.DateField(_("Expiration date"), null=True, blank=True)

    autocomplete_search_field = "file"

    def autocomplete_label(self):
        return f"{self.file.name} - {self.category} - {self.article or self.issue} ({self.status})"

    panels = [
        FieldPanel("file"),
    ]

    def __str__(self):
        return self.file.name

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

    base_form_class = UploadPackageForm

    class Meta:
        permissions = (
            (FINISH_DEPOSIT, _("Can finish deposit")),
            (ACCESS_ALL_PACKAGES, _("Can access all packages from all users")),
            (ASSIGN_PACKAGE, _("Can assign package")),
        )

    @classmethod
    def add_validation_result(
        cls, package_id, error_category=None, status=None, message=None, data=None
    ):
        package = cls.objects.get(pk=package_id)
        val_res = package._add_validation_result(error_category, status, message, data)
        return val_res

    def _add_validation_result(
        self, error_category=None, status=None, message=None, data=None
    ):
        val_res = ValidationResult.create(error_category, self, status, message, data)
        self.update_status(val_res)
        return val_res

    def update_status(self, validation_result):
        if validation_result.status == choices.VS_DISAPPROVED:
            self.status = choices.PS_REJECTED
            self.save()

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

    def check_resolutions(self):
        try:
            item = self.validationresult_set.filter(
                status=choices.VS_DISAPPROVED,
                resolution__action__in=[choices.ER_ACTION_TO_FIX, ""],
            )[0]
            self.status = choices.PS_PENDING_CORRECTION
        except IndexError:
            self.status = choices.PS_READY_TO_BE_FINISHED
        self.save()
        return self.status

    def check_opinions(self):
        try:
            item = self.validationresult_set.filter(
                status=choices.VS_DISAPPROVED,
                analysis__opinion__in=[choices.ER_OPINION_FIX_DEMANDED, ""],
            )[0]
            self.status = choices.PS_PENDING_CORRECTION
        except IndexError:
            self.status = choices.PS_ACCEPTED
        self.save()
        return self.status

    def check_finish(self):
        if self.status == choices.PS_READY_TO_BE_FINISHED:
            self.status = choices.PS_QA
            self.save()
            return True

        return False

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
            expiration_date=str(expiration_date),
        )


class QAPackage(Package):
    class Meta:
        proxy = True


class ValidationResult(models.Model):
    id = models.AutoField(primary_key=True)
    category = models.CharField(
        _("Error category"),
        max_length=32,
        choices=choices.VALIDATION_ERROR_CATEGORY,
        null=False,
        blank=False,
    )
    data = models.JSONField(_("Error data"), default=dict, null=True, blank=True)
    message = models.TextField(_("Error message"), null=True, blank=True)
    status = models.CharField(
        _("Status"),
        max_length=16,
        choices=choices.VALIDATION_STATUS,
        null=True,
        blank=True,
    )

    package = models.ForeignKey(
        "Package", on_delete=models.CASCADE, null=False, blank=False
    )

    def __str__(self):
        return "-".join(
            [
                str(self.id),
                self.package.file.name,
                self.category,
                self.status,
            ]
        )

    def report_name(self):
        return choices.VALIDATION_DICT_ERROR_CATEGORY_TO_REPORT[self.category]

    panels = [
        MultiFieldPanel(
            [
                AutocompletePanel("package"),
                FieldPanel("category"),
            ],
            heading=_("Identification"),
            classname="collapsible",
        ),
        MultiFieldPanel(
            [
                FieldPanel("status"),
                FieldPanel("data"),
                FieldPanel("message"),
            ],
            heading=_("Content"),
            classname="collapsible",
        ),
    ]

    class Meta:
        permissions = (
            (SEND_VALIDATION_ERROR_RESOLUTION, _("Can send error resolution")),
            (ANALYSE_VALIDATION_ERROR_RESOLUTION, _("Can analyse error resolution")),
        )

    base_form_class = ValidationResultForm

    @classmethod
    def create(cls, error_category, package, status=None, message=None, data=None):
        val_res = ValidationResult()
        val_res.category = error_category
        val_res.package = package
        val_res.status = status
        val_res.message = message
        val_res.data = data
        val_res.save()
        return val_res

    def update(self, error_category, status=None, message=None, data=None):
        self.category = error_category
        self.status = status
        self.message = message
        self.data = data
        self.save()

        self.package.update_status(self)

    @classmethod
    def add_resolution(cls, user, data):
        validation_result = cls.objects.get(pk=data["validation_result_id"].value())

        try:
            opinion = data["opinion"].value()
            return ErrorResolutionOpinion.create_or_update(
                user=user,
                validation_result=validation_result,
                opinion=opinion,
                guidance=data["guidance"].value(),
            )
        except KeyError:
            return ErrorResolution.create_or_update(
                user=user,
                validation_result=validation_result,
                action=data["action"].value(),
                rationale=data["rationale"].value(),
            )


class ErrorResolution(CommonControlField):
    validation_result = models.OneToOneField(
        "ValidationResult",
        to_field="id",
        primary_key=True,
        related_name="resolution",
        on_delete=models.CASCADE,
    )
    action = models.CharField(
        _("Action"),
        max_length=32,
        choices=choices.ERROR_RESOLUTION_ACTION,
        default=choices.ER_ACTION_TO_FIX,
        null=True,
        blank=True,
    )
    rationale = models.TextField(_("Rationale"), null=True, blank=True)

    panels = [
        FieldPanel("action"),
        FieldPanel("rationale"),
    ]

    @classmethod
    def get(cls, validation_result):
        return cls.objects.get(validation_result=validation_result)

    @classmethod
    def create(cls, user, validation_result, action, rationale):
        obj = cls()
        obj.creator = user
        obj.created = datetime.now()
        obj.validation_result = validation_result
        obj.action = action
        obj.rationale = rationale
        obj.save()
        return obj

    @classmethod
    def create_or_update(cls, user, validation_result, action, rationale):
        try:
            obj = cls.get(validation_result)
            obj.updated = datetime.now()
            obj.updated_by = user
            obj.action = action
            obj.rationale = rationale
            obj.save()
        except cls.DoesNotExist:
            obj = cls.create(user, validation_result, action, rationale)
        return obj


class ErrorResolutionOpinion(CommonControlField):
    validation_result = models.OneToOneField(
        "ValidationResult",
        to_field="id",
        primary_key=True,
        related_name="analysis",
        on_delete=models.CASCADE,
    )
    opinion = models.CharField(
        _("Opinion"),
        max_length=32,
        choices=choices.ERROR_RESOLUTION_OPINION,
        null=True,
        blank=True,
    )
    guidance = models.TextField(_("Guidance"), max_length=512, null=True, blank=True)

    panels = [
        FieldPanel("opinion"),
        FieldPanel("guidance"),
    ]

    @classmethod
    def get(cls, validation_result):
        return cls.objects.get(validation_result=validation_result)

    @classmethod
    def create(cls, user, validation_result, opinion, guidance):
        obj = cls()
        obj.creator = user
        obj.created = datetime.now()
        obj.validation_result = validation_result
        obj.opinion = opinion
        obj.guidance = guidance
        obj.save()
        return obj

    @classmethod
    def create_or_update(cls, user, validation_result, opinion, guidance):
        try:
            obj = cls.get(validation_result)
            obj.updated = datetime.now()
            obj.updated_by = user
            obj.save()
        except cls.DoesNotExist:
            obj = cls.create(user, validation_result, opinion, guidance)
        return obj


class ReviewPdf(CommonControlField):
    marks = models.BooleanField(default=False, verbose_name=_("Marks by the editor/author."))
    bibliographic_caption = models.BooleanField(default=False, verbose_name=_("Bibliographic caption with journal information such as volume, number, supplement, special issue and year of publication."))

    table_of_contents = models.BooleanField(default=False, verbose_name=_("For regular publication, Table of contents pagination matches the PDF."))
    pagination = models.BooleanField(default=False, verbose_name=_("For AOP, Pagination appears as 1-X (it cannot have sequential pagination)."))
    elocation = models.BooleanField(default=False, verbose_name=_("For PC, Contains elocation-id (unique for each document) also optional pagination for 1-X printing (cannot have sequential pagination)."))
    periodicity = models.BooleanField(default=False, verbose_name=_("For regular publication, Periodicity information is included."))
    doi = models.BooleanField(default=False, verbose_name=_("For all types of publication, DOI is included in the PDF (mandatory). The DOI number must be unique for each document."))
    doi_translation = models.BooleanField(default=False, verbose_name=_("For all types of publication, When there is a translation if there is a different DOI for translation. If it appears in the PDF, it must be marked in the XML."))
    doi_characters = models.BooleanField(default=False, verbose_name=_("There are no characters that could \"break\" the DOI registration in CrossRef."))
    license = models.BooleanField(default=False, verbose_name=_("For all types of publication, Creative Commons (CC) license is included in the PDF (required)."))
    history_dates = models.BooleanField(default=False, verbose_name=_("For all types of publication, Articles that have undergone peer review must contain at least the complete history dates (day + month + year) of acceptance and approval."))
    label_affiliation = models.BooleanField(default=False, verbose_name=_("For all modalities, Affiliation is correct and has its respective label between author and affiliation (mandatory)."))
    orcid = models.BooleanField(default=False, verbose_name=_("For all modalities, There is at least one author with ORCID (any author), if so, check if there is a visible number (In the model: 0000-0000-0000-0000 [allows letter]) or ORCID icon linked to the page from the author's ORCID."))
    taxonomy = models.BooleanField(default=False, verbose_name=_("Exists taxonomy information."))
    role = models.BooleanField(default=False, verbose_name=_("If there is an indication of author contributions, the marking in <role> is correct."))
    credit = models.BooleanField(default=False, verbose_name=_("If Taxonomy CRediT, Tag attribute was marked correctly."))
    availability = models.BooleanField(default=False, verbose_name=_("Data availability information has been marked with the correct tags."))
    opinion = models.BooleanField(default=False, verbose_name=_("When an opinion is published, Marking follows guidelines and correct labeling."))
    preprint = models.BooleanField(default=False, verbose_name=_("Preprint information was marked with the correct tags."))

    panels_general = [
        FieldPanel("marks"),
        FieldPanel("bibliographic_caption"),
    ]

    panels_pagination = [
        FieldPanel("table_of_contents"),
        FieldPanel("pagination"),
        FieldPanel("elocation"),
    ]

    panels_doi = [
        FieldPanel("doi"),
        FieldPanel("doi_translation"),
        FieldPanel("doi_characters"),
    ]

    panels_license = [
        FieldPanel("license"),
    ]

    panels_history_dates = [
        FieldPanel("history_dates"),
    ]

    panels_label_affiliation = [
        FieldPanel("label_affiliation"),
    ]

    panels_orcid = [
        FieldPanel("orcid"),
    ]

    panels_credit = [
        FieldPanel("taxonomy"),
        FieldPanel("role"),
        FieldPanel("credit"),
    ]

    panels_availability = [
        FieldPanel("availability"),
    ]


    edit_handler = TabbedInterface(
        [
            ObjectList(panels_general, heading=_("General")),
            ObjectList(panels_pagination, heading=_("Pagination")),
            ObjectList(panels_doi, heading=_("DOI")),
            ObjectList(panels_license, heading=_("License")),
            ObjectList(panels_history_dates, heading=_("History dates")),
            ObjectList(panels_label_affiliation, heading=_("Label affiliation")),
            ObjectList(panels_orcid, heading=_("ORCID")),
            ObjectList(panels_credit, heading=_("Author contributions (CRediT)")),
            ObjectList(panels_availability, heading=_("Data availability")),
        ]
    )
