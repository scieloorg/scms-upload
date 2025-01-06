from datetime import datetime

from wagtail.models import Orderable
from django.db import IntegrityError, models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel

from article.models import Article
from collection.models import Collection
from core.models import CommonControlField
from publication.choices import VERIFY_HTTP_ERROR_CODE


class ArticleAvailability(ClusterableModel, CommonControlField):
    """
    Modelo para armazenar o status de disponibilidade nos sites,
    tanto na nova versao, quanto na antiga, do scielo.br.
    """

    article = models.ForeignKey(
        Article,
        on_delete=models.SET_NULL,
        null=True,
        unique=True,
    )
    panels = [FieldPanel("article"), InlinePanel("scielo_url")]

    @classmethod
    def get(
        cls,
        article,
    ):
        return cls.objects.get(article=article)

    @classmethod
    def create(
        cls,
        user,
        article,
    ):
        try:
            obj = cls(
                article=article,
                creator=user,
            )
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(article=article)


class ScieloURLStatus(CommonControlField, Orderable):
    article_availability = ParentalKey(
        "ArticleAvailability",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scielo_url",
    )
    url = models.URLField(max_length=500, unique=True)
    status = models.CharField(
        max_length=80, choices=VERIFY_HTTP_ERROR_CODE, null=True, blank=True
    )
    available = models.BooleanField(default=False)

    def update(
        self,
        available,
        status,
        check_date,
    ):
        self.updated = check_date or datetime.now()
        self.status = status
        self.available = available
        self.save()
        return self

    @classmethod
    def get(
        cls,
        article,
        url,
    ):
        return cls.objects.get(article_availability__article=article, url=url)

    @classmethod
    def create(
        cls,
        article,
        url,
        status,
        available,
        user,
    ):
        try:
            article_availability = ArticleAvailability.get(article=article)
        except ArticleAvailability.DoesNotExist:
            article_availability = ArticleAvailability.create(
                user=user, article=article
            )
        obj = cls(
            article_availability=article_availability,
            url=url,
            status=status,
            available=available,
            creator=user,
        )
        obj.save()
        return obj

    @classmethod
    def create_or_update(
        cls,
        user,
        article,
        url,
        check_date,
        status,
        available,
    ):
        try:
            obj = cls.get(article=article, url=url)
            obj.update(
                check_date=check_date,
                available=available,
                status=status,
            )
            return obj
        except cls.DoesNotExist:
            return cls.create(
                article=article,
                url=url,
                status=status,
                available=available,
                user=user,
            )


def upload_path_for_verification_files(instance, filename):
    try:
        return f"verification_article_files/{instance.collection.acron}"
    except:
        return f"verification_article_files/{filename}"


class CollectionVerificationFile(CommonControlField):
    """
        Modelo para armazenar o arquivo que contém os pids v2 da migração de acordo com a coleção
    """
    collection = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        unique=True,
    )
    uploaded_file = models.FileField(upload_to=upload_path_for_verification_files)

    class Meta:
        unique_together = [("collection", "uploaded_file")]

    def __str__(self):
        return f"{self.collection} - {self.uploaded_file}"


class MissingArticle(CommonControlField):
    collection_file = models.ForeignKey(
        CollectionVerificationFile,
        on_delete=models.SET_NULL,
        null=True,
    )
    pid_v2 = models.CharField(_("PID v2"), max_length=23, blank=True, null=True)

    def get_collection_name(self,):
        if self.collection_file and self.collection_file.collection:
            return self.collection_file.collection.name 
        
    get_collection_name.short_description = "Collection name"

    @classmethod
    def get(
        cls,
        collection_file,
        pid_v2,
    ):
        return cls.objects.get(collection_file=collection_file, pid_v2=pid_v2)

    @classmethod
    def create(
        cls,
        collection_file,
        pid_v2,
        user,
    ):
        try:
            obj = cls(
                collection_file=collection_file,
                pid_v2=pid_v2,
                creator=user,
            )
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(collection_file=collection_file, pid_v2=pid_v2)

    @classmethod
    def create_or_update(
        cls,
        collection_file,
        pid_v2,
        user,
    ):
        try:
            return cls.get(collection_file=collection_file, pid_v2=pid_v2)
        except cls.DoesNotExist:
            return cls.create(collection_file=collection_file, pid_v2=pid_v2, user=user)
