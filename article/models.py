import logging
import datetime

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.fields import RichTextField
from wagtail.admin.panels import (
    FieldPanel,
    InlinePanel,
    MultiFieldPanel,
)
from wagtailautocomplete.edit_handlers import AutocompletePanel
from wagtail.models import Orderable

from core.models import CommonControlField
from doi.models import DOIWithLang
from issue.models import Issue
from journal.models import Journal, OfficialJournal
from package.models import SPSPkg

from researcher.models import Researcher

from . import choices
from .forms import ArticleForm, RelatedItemForm, RequestArticleChangeForm
from .permission_helper import MAKE_ARTICLE_CHANGE, REQUEST_ARTICLE_CHANGE

User = get_user_model()


class Article(ClusterableModel, CommonControlField):
    """
    No contexto de Upload, Article deve conter o mínimo de campos,
    suficiente para o processo de ingresso / validações,
    pois os dados devem ser obtidos do XML
    """

    sps_pkg = models.ForeignKey(
        SPSPkg, blank=True, null=True, on_delete=models.SET_NULL
    )
    # PID v3
    pid_v3 = models.CharField(_("PID v3"), max_length=23, blank=True, null=True)

    # Article type
    article_type = models.CharField(
        _("Article type"),
        max_length=32,
        choices=choices.ARTICLE_TYPE,
        blank=False,
        null=False,
    )

    # Article status
    status = models.CharField(
        _("Article status"),
        max_length=32,
        choices=choices.ARTICLE_STATUS,
        blank=True,
        null=True,
    )

    # Page
    elocation_id = models.CharField(
        _("Elocation ID"), max_length=64, blank=True, null=True
    )
    fpage = models.CharField(_("First page"), max_length=16, blank=True, null=True)
    lpage = models.CharField(_("Last page"), max_length=16, blank=True, null=True)

    # External models
    issue = models.ForeignKey(Issue, blank=True, null=True, on_delete=models.SET_NULL)
    journal = models.ForeignKey(
        Journal, blank=True, null=True, on_delete=models.SET_NULL
    )
    related_items = models.ManyToManyField(
        "self", symmetrical=False, through="RelatedItem", related_name="related_to"
    )

    panel_article_ids = MultiFieldPanel(
        heading="Article identifiers", classname="collapsible"
    )
    panel_article_ids.children = [
        # FieldPanel("pid_v2"),
        FieldPanel("pid_v3"),
        # FieldPanel("aop_pid"),
        InlinePanel(relation_name="doi_with_lang", label="DOI with Language"),
    ]

    panel_article_details = MultiFieldPanel(
        heading="Article details", classname="collapsible"
    )
    panel_article_details.children = [
        FieldPanel("article_type"),
        FieldPanel("status"),
        InlinePanel(relation_name="title_with_lang", label="Title with Language"),
        InlinePanel(relation_name="author", label="Authors"),
        FieldPanel("elocation_id"),
        FieldPanel("fpage"),
        FieldPanel("lpage"),
    ]

    panels = [
        panel_article_ids,
        panel_article_details,
        FieldPanel("issue", classname="collapsible"),
    ]

    class Meta:
        indexes = [
            models.Index(fields=["pid_v3"]),
        ]

        permissions = (
            (MAKE_ARTICLE_CHANGE, _("Can make article change")),
            (REQUEST_ARTICLE_CHANGE, _("Can request article change")),
        )

    base_form_class = ArticleForm

    autocomplete_search_field = "sps_pkg__sps_pkg_name"

    def autocomplete_label(self):
        return self.sps_pkg.sps_pkg_name

    def __str__(self):
        return f"{self.sps_pkg.sps_pkg_name}"

    @property
    def data(self):
        # TODO completar com itens que identifique o artigo
        return dict(
            xml=self.sps_pkg and self.sps_pkg.xml_uri,
            issue=self.issue.data,
            journal=self.journal.data,
            pid_v3=self.pid_v3,
            created=self.created.isoformat(),
            updated=self.updated.isoformat(),
        )

    @classmethod
    def get(cls, pid_v3):
        if pid_v3:
            return cls.objects.get(pid_v3=pid_v3)
        raise ValueError("Article.get requires pid_v3")

    @classmethod
    def create_or_update(cls, user, sps_pkg):
        if not sps_pkg or sps_pkg.pid_v3 is None:
            raise ValueError("create_article requires sps_pkg with pid_v3")

        try:
            obj = cls.get(sps_pkg.pid_v3)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.pid_v3 = sps_pkg.pid_v3
            obj.creator = user

        obj.sps_pkg = sps_pkg
        obj.save()

        return obj

    # def link_to_article_proc(self, user, force_update):
    #     qa_ws_status = None
    #     if force_update:
    #         qa_ws_status = collection_choices.WS_READY_TO_QA
    #     for collection in self.collections:
    #         article_proc = ArticleProc.objects.get(collection=collection)
    #         article_proc.article = self
    #         article_proc.save()

    # @property
    # def collections(self):
    #     if not self.journal:
    #         raise ValueError("Unable to get collections. Missing article.journal")
    #     for journal_proc in JournalProc.objects.filter(journal=self.journal).iterator():
    #         yield journal_proc.collection

    def add_type(self, article_type):
        self.article_type = article_type

    def add_related_item(self, target_doi, target_article_type):
        self.save()
        # TODO
        # item = RelatedItem()
        # item.item_type = target_article_type
        # item.source_article = self
        # item.target_article = target_location
        # item.save()
        # self.related_items.add(item)

    def add_pages(self, fpage=None, fpage_seq=None, lpage=None, elocation_id=None):
        self.fpage = fpage
        self.fpage_seq = fpage_seq
        self.lpage = lpage
        self.elocation_id = elocation_id

    def add_issue(self, user):
        xml_with_pre = self.sps_pkg.xml_with_pre
        self.issue = Issue.get(
            journal=self.journal,
            volume=xml_with_pre.volume,
            supplement=xml_with_pre.suppl,
            number=xml_with_pre.number,
        )

    def add_journal(self, user):
        xml_with_pre = self.sps_pkg.xml_with_pre
        self.journal = Journal.get(
            official_journal=OfficialJournal.get(
                issn_electronic=xml_with_pre.journal_issn_electronic,
                issn_print=xml_with_pre.journal_issn_print,
            ),
        )


class ArticleAuthor(Orderable, Researcher):
    author = ParentalKey("Article", on_delete=models.CASCADE, related_name="author")


class ArticleDOIWithLang(Orderable, DOIWithLang):
    doi_with_lang = ParentalKey(
        "Article", on_delete=models.CASCADE, related_name="doi_with_lang"
    )


class Title(CommonControlField):
    title = models.TextField(_("Title"))
    lang = models.CharField(_("Language"), max_length=64)

    panels = [
        FieldPanel("title"),
        FieldPanel("lang"),
    ]

    def __str__(self):
        return f"{self.lang.upper()}: {self.title}"

    class Meta:
        abstract = True


class ArticleTitle(Orderable, Title):
    title_with_lang = ParentalKey(
        "Article", on_delete=models.CASCADE, related_name="title_with_lang"
    )


class RelatedItem(CommonControlField):
    item_type = models.CharField(
        _("Related item type"),
        max_length=32,
        choices=choices.RELATED_ITEM_TYPE,
        blank=False,
        null=False,
    )
    source_article = models.ForeignKey(
        "Article",
        related_name="source_article",
        on_delete=models.CASCADE,
        null=False,
        blank=False,
    )
    target_article = models.ForeignKey(
        "Article",
        related_name="target_article",
        on_delete=models.CASCADE,
        null=False,
        blank=False,
    )

    panel = [
        FieldPanel("item_type"),
        FieldPanel("source_article"),
        FieldPanel("target_article"),
    ]

    def __str__(self):
        return f"{self.source_article} - {self.target_article} ({self.item_type})"

    base_form_class = RelatedItemForm


class RequestArticleChange(CommonControlField):
    deadline = models.DateField(_("Deadline"), blank=False, null=False)

    change_type = models.CharField(
        _("Change type"),
        max_length=32,
        choices=choices.REQUEST_CHANGE_TYPE,
        blank=False,
        null=False,
    )
    comment = RichTextField(_("Comment"), max_length=512, blank=True, null=True)

    article = models.ForeignKey(
        Article, on_delete=models.CASCADE, blank=True, null=True
    )
    pid_v3 = models.CharField(_("PID v3"), max_length=23, blank=True, null=True)
    demanded_user = models.ForeignKey(
        User, on_delete=models.CASCADE, blank=False, null=False
    )

    panels = [
        FieldPanel("pid_v3", classname="collapsible"),
        FieldPanel("deadline", classname="collapsible"),
        FieldPanel("change_type", classname="collapsible"),
        AutocompletePanel("demanded_user", classname="collapsible"),
        FieldPanel("comment", classname="collapsible"),
    ]

    def __str__(self) -> str:
        return f"{self.article or self.pid_v3} - {self.deadline}"

    base_form_class = RequestArticleChangeForm


class CheckArticleAvailability(CommonControlField):
    """
        Modelo para armazenar o status de disponibilidade nos sites,
        tanto na nova versao, quanto na antiga, do scielo.br.
    """
    article = models.ForeignKey(
        Article, 
        on_delete=models.SET_NULL,
        null=True,
    )
    site_status = models.ManyToManyField(
        "ScieloSiteStatus"
    )

    def __str__(self):
        return f"{self.article.pid_v3}"
    
    @classmethod
    def get(cls, article):
        return cls.objects.get(article=article)
    
    def create_or_update_scielo_site_status(
        self,
        url,
        status,
        user
    ):
        obj = ScieloSiteStatus.create_or_update(
            url=url,
            status=status,
            user=user,
        )
        self.site_status.add(obj) 
        self.save()


    @classmethod
    def create(
        cls,
        article,
        status,
        url,
        user,

    ):
        obj = cls(
            article=article,
            creator=user,
        )
        obj.save()
        obj.create_or_update_scielo_site_status(
            url=url,
            status=status,
            user=user,
        )
        return obj

    @classmethod
    def create_or_update(cls,
        article,
        status,
        url,
        user,            
    ):
        try:
            obj = cls.get(article=article)
            obj.create_or_update_scielo_site_status(
            url=url,
            status=status,
            user=user,
        )
            return obj
        except cls.DoesNotExist:
            cls.create(
                article=article,
                status=status,
                url=url,
                user=user
            )

class ScieloSiteStatus(CommonControlField):
    check_date = models.DateTimeField(null=True, blank=True)
    url_site_scielo = models.SlugField(max_length=500, unique=True)
    available = models.BooleanField(default=False)

    def update(
        self,
        status,
    ):
        self.check_date = datetime.datetime.now()
        self.available = status
        self.save()
        return self


    @classmethod
    def get(cls, url):
        return cls.objects.get(url_site_scielo=url)


    @classmethod
    def create(
        cls,
        url,
        status,
        user,
    ):
        obj = cls(
            check_date=datetime.datetime.now(),
            url_site_scielo=url,
            available=status,
            creator=user
        )
        obj.save()
        return obj

    @classmethod
    def create_or_update(
        cls,
        url,
        status,
        user,
    ):
        try:
            obj = cls.get(url=url)
            obj.update(status=status)
            return obj
        except cls.DoesNotExist:
            return cls.create(
                url=url,
                status=status,
                user=user,
            )