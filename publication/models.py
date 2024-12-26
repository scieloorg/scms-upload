from datetime import datetime

from wagtail.models import Orderable
from django.db import IntegrityError, models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel

from article.models import Article
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
