import csv
import hashlib
import os

from django.core.files.base import ContentFile
from django.db import models, IntegrityError
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel

from article.models import Article
from core.forms import CoreAdminModelForm
from core.models import CommonControlField


def csv_crossref_directory_path(instance, filename):
    subdir = "csv_report_crossref"
    path_parts = [
        subdir,
    ]
    filename_hash = hashlib.sha256(filename.encode()).hexdigest()[:10]
    path_parts.append(f"{filename_hash}.csv")
    return os.path.join(*path_parts)


def xml_crossref_directory_path(instance, filename):
    subdir = "file_xml_crossref"
    try:
        path_parts = [
            subdir,
            instance.article.issue.publication_year,
            instance.article.sps_pkg.sps_pkg_name,
            filename,
        ]
    except AttributeError:
        path_parts = [
            subdir,
            instance.article.sps_pkg_name.sps_pkg_name,
            filename
        ]
    return os.path.join(*path_parts)


class UserAccountCrossref(CommonControlField):
    username = models.CharField(max_length=50, blank=False, null=False)
    password = models.CharField(max_length=50, blank=False, null=False)

    panels = [
        FieldPanel("username"),
        FieldPanel("password"),
    ]

    base_form_class = CoreAdminModelForm


class ContentRegistrationFee(CommonControlField):
    record_type = models.CharField(
        max_length=50,
        unique=True,
        blank=False,
        null=False,
    )
    fee_current_year = models.DecimalField(
        max_digits=6,
        decimal_places=2,
    )
    fee_back_year = models.DecimalField(
        max_digits=6,
        decimal_places=2,
    )

    panels = [
        FieldPanel("record_type"),
        FieldPanel("fee_current_year"),
        FieldPanel("fee_back_year"),
    ]

    @classmethod
    def load(cls, user):
        with open("./crossref/fixture/registration_fee.csv") as csvfile:
            fees = csv.DictReader(
                csvfile,
                fieldnames=["record_type", "fee_current_year", "fee_back_year"],
                delimiter=";",
            )
            for fee in fees:
                cls.create_or_update(
                    record_type=fee["record_type"],
                    fee_current_year=fee["fee_current_year"],
                    fee_back_year=fee["fee_back_year"],
                    user=user,
                )

    @classmethod
    def get(
        cls,
        record_type,
    ):
        if not record_type:
            return ValueError(
                "ContentRegistrationFee.get require record_type paramenter"
            )
        return cls.objects.get(record_type=record_type)

    @classmethod
    def create(
        cls,
        record_type,
        fee_current_year,
        fee_back_year,
        user,
    ):
        try:
            obj = cls(
                record_type=record_type,
                fee_current_year=fee_current_year,
                fee_back_year=fee_back_year,
                creator=user,
            )
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(record_type=record_type)

    @classmethod
    def create_or_update(
        cls,
        record_type,
        fee_current_year,
        fee_back_year,
        user,
    ):
        try:
            return cls.get(record_type=record_type)
        except cls.DoesNotExist:
            return cls.create(
                record_type=record_type,
                fee_current_year=fee_current_year,
                fee_back_year=fee_back_year,
                user=user,
            )


class XMLCrossref(CommonControlField):
    file = models.FileField(
        upload_to=xml_crossref_directory_path,
        blank=False,
        null=False,
    )
    article = models.ForeignKey(
        "article.Article",
        on_delete=models.SET_NULL,
        blank=False,
        null=True,
        related_name="xml_crossref_article",
    )

    class Meta:
        unique_together = [("file", "article")]

    @classmethod
    def get(
        cls,
        file,
        article,
    ):
        if not file and not article:
            return ValueError("XMLCrossref.get requires file and article paramenters")
        return cls.objects.get(file=file, article=article)

    @classmethod
    def create(
        cls,
        file,
        article,
        filename,
        user,
    ):
        try:
            obj = cls(
                article=article,
                creator=user,
            )
            obj.save()
            obj.save_file(filename, file)
            return obj
        except IntegrityError:
            return cls.get(file=file, article=article)

    @classmethod
    def create_or_update(
        cls,
        file,
        article,
        filename,
        user,
    ):
        try:
            return cls.get(file=file, article=article)
        except cls.DoesNotExist:
            return cls.create(
                file=file,
                article=article,
                filename=filename,
                user=user,
            )

    def save_file(self, filename, content):
        if self.file:
            try:
                self.file.delete()
            except Exception as e:
                pass
            self.file.save(filename, ContentFile(content))
            self.save()

    @property
    def data(self):
        return {
            "depositor_name": self.depositor_name or "depositor_name",
            "depositor_email_address": self.depositor_email_address
            or "depositor_email_address",
            "registrant": self.registrant or "registrant",
        }

class CrossrefConfiguration(CommonControlField):
    prefix = models.CharField(
        _("Prefix"), 
        null=True, 
        blank=True, 
        max_length=10,
    )
    depositor_name = models.CharField(
        _("Depositor Name"),
        null=True,
        blank=True,
        max_length=64,
    )
    depositor_email_address = models.EmailField(
        _("Depositor e-mail"),
        null=True,
        blank=True,
        max_length=64,
    )
    registrant = models.CharField(
        _("Registrant"),
        null=True,
        blank=True,
        max_length=64,
    )

    base_form_class = CoreAdminModelForm
    panels = [
        FieldPanel("depositor_name"),
        FieldPanel("depositor_email_address"),
        FieldPanel("registrant"),
        FieldPanel("prefix"),
    ]

    @property
    def data(self):
        return {
            "depositor_name": self.depositor_name or "depositor_name",
            "depositor_email_address": self.depositor_email_address or "depositor_email_address",
            "registrant": self.registrant or "registrant",
        }

    @classmethod
    def get_data(cls, prefix):
        try:
            return cls.objects.get(prefix=prefix).data
        except cls.DoesNotExist:
            return cls().data


class ReportCrossref(CommonControlField):
    file = models.FileField(
        upload_to=csv_crossref_directory_path,
        blank=False,
        null=False,
    )
