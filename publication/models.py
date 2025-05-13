import logging
from datetime import datetime

from article.models import Article
from collection.models import Collection
from core.models import CommonControlField
from core.utils.requester import fetch_data, NonRetryableError
from django.db import IntegrityError, models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtail.models import Orderable


def calculate_percentage(value, total):
    if total:
        return round(value * 100 / total, 2)
    return 0


def check_url(url, timeout=None):
    try:
        fetch_data(url, timeout=timeout or 2)
    except NonRetryableError as e:
        return False
    else:
        return True


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
    published_by = models.CharField(
        _("published by"), max_length=30, null=True, blank=True)
    publication_rule = models.CharField(
        _("publication rule"), max_length=10, null=True, blank=True)
    published_percentage = models.DecimalField(
        verbose_name=_("Published percentual"),
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text=_("0-100"),
    )
    panels = [
        FieldPanel("publication_rule"),
        FieldPanel("published_by"),
        InlinePanel("scielo_url", label="URLs", classname="collapsible"),
    ]

    def __str__(self):
        return str(self.article)

    @classmethod
    def get(cls, article):
        return cls.objects.get(article=article)

    @classmethod
    def create(
        cls,
        user,
        article,
        published_by=None,
        publication_rule=None,
        website_url=None,
        timeout=None,
    ):
        try:
            obj = cls(
                article=article,
                creator=user,
                published_by=published_by,
                publication_rule=publication_rule,
            )
            obj.save()
            if website_url:
                obj.create_or_update_urls(user, website_url, timeout)
            return obj
        except IntegrityError:
            return cls.get(article=article)

    @classmethod
    def create_or_update(
        cls,
        user,
        article,
        published_by=None,
        publication_rule=None,
        website_url=None,
        timeout=None
    ):
        try:
            obj = cls.get(article=article)

            obj.published_by = obj.published_by or published_by
            obj.publication_rule = obj.publication_rule or publication_rule
            if published_by or publication_rule:
                obj.save()
            if website_url:
                obj.create_or_update_urls(user, website_url, timeout)
            return obj
        except cls.DoesNotExist:
            return cls.create(
                user, article, published_by, publication_rule, website_url, timeout
            )

    def create_or_update_urls(self, user, website_url, timeout=None):
        for url in self.article.get_urls(website_url):
            ScieloURLStatus.create_or_update(
                user=user,
                article=self.article,
                url=url,
                timeout=timeout,
            )
        self.update_published_percentage()

    def update_published_percentage(self, save):
        self.published_percentage = calculate_percentage(
            self.article.scielo_url.filter(available=True).count(),
            self.article.scielo_url.count()
        )
        self.save()

    def retry(self, user, website_url, timeout=None):
        for item in ScieloURLStatus.objects.filter(
            article_availability__article=self.article,
            available=False,
        ):
            item.update(user, timeout)
        self.update_published_percentage()


class ScieloURLStatus(CommonControlField, Orderable):
    article_availability = ParentalKey(
        "ArticleAvailability",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scielo_url",
    )
    url = models.URLField(max_length=500, unique=True)
    available = models.BooleanField(default=False)

    panels = [FieldPanel("url"), FieldPanel("available", read_only=True)]

    @classmethod
    def get(cls, url):
        return cls.objects.get(url=url)

    @classmethod
    def create(
        cls,
        user,
        article,
        url,
        timeout=None,
    ):
        try:
            article_availability = ArticleAvailability.create_or_update(user, article)
            obj = cls(
                article_availability=article_availability,
                url=url,
                available=check_url(url, timeout),
                creator=user,
            )
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(url)

    @classmethod
    def create_or_update(
        cls,
        user,
        article,
        url,
        timeout=None,
    ):
        try:
            obj = cls.get(url=url)
            obj.update(user, timeout)
            return obj
        except cls.DoesNotExist:
            return cls.create(
                article=article,
                url=url,
                user=user,
                timeout=timeout or 2
            )

    def update(self, user, timeout=None):
        self.available = check_url(self.url, timeout)
        self.updated_by = user
        self.save()


def upload_path_for_verification_files(instance, filename):
    try:
        return f"verification_article_files/{instance.collection.acron}"
    except:
        return f"verification_article_files/{filename}"
