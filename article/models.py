from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from collection.models import Collection
from core.models import CommonControlField
from doi.models import DOIWithLang
from issue.models import Issue
from journal.models import Journal, OfficialJournal
from researcher.models import Researcher

from . import choices
from .forms import ArticleForm, RelatedItemForm, RequestArticleChangeForm
from .permission_helper import MAKE_ARTICLE_CHANGE, REQUEST_ARTICLE_CHANGE

User = get_user_model()


class CollectionArticleId(ClusterableModel, CommonControlField):
    # Armazena os IDs dos artigos no contexto de cada coleção
    # serve para conseguir recuperar artigos pelo ID do site clássico
    collection = models.ForeignKey(
        Collection, on_delete=models.SET_NULL, null=True, blank=True
    )
    pid_v3 = models.CharField(_("PID v3"), max_length=23, blank=True, null=True)
    pid_v2 = models.CharField(_("PID v2"), max_length=23, blank=True, null=True)
    aop_pid = models.CharField(_("AOP PID"), max_length=23, blank=True, null=True)

    @classmethod
    def get(cls, pid_v3=None, pid_v2=None, aop_pid=None, collection=None):
        if pid_v3:
            return cls.objects.get(pid_v3=pid_v3)

        if collection:
            if pid_v2:
                return cls.objects.get(
                    Q(aop_pid=pid_v2) | Q(pid_v2=pid_v2), collection=collection
                )
            if aop_pid:
                return cls.objects.get(
                    Q(aop_pid=aop_pid) | Q(pid_v2=aop_pid), collection=collection
                )

        if pid_v2:
            return cls.objects.get(Q(aop_pid=pid_v2) | Q(pid_v2=pid_v2))
        if aop_pid:
            return cls.objects.get(Q(aop_pid=aop_pid) | Q(pid_v2=aop_pid))

    @classmethod
    def create_or_update(
        cls, pid_v3=None, pid_v2=None, aop_pid=None, collection=None, creator=None
    ):
        try:
            obj = cls.get(
                pid_v3=pid_v3, pid_v2=pid_v2, aop_pid=aop_pid, collection=collection
            )
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = creator
            obj.created = datetime.utcnow()
        obj.collection = collection or obj.collection
        obj.aop_pid = aop_pid or obj.aop_pid
        obj.pid_v3 = pid_v3 or obj.pid_v3
        obj.pid_v2 = pid_v2 or obj.pid_v2
        obj.save()
        return obj


class Article(ClusterableModel, CommonControlField):
    # PID v3
    pid_v3 = models.CharField(_("PID v3"), max_length=23, blank=True, null=True)

    # Identificadores no contexto das coleção / compatibilidade com legado
    aids = models.ManyToManyField(CollectionArticleId)

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

    @classmethod
    def get(cls, pid_v3=None, pid_v2=None, aop_pid=None, collection=None):
        if pid_v3:
            return cls.objects.get(pid_v3=pid_v3)

        if collection:
            if pid_v2:
                return cls.objects.get(
                    Q(aids__aop_pid=pid_v2) | Q(aids__pid_v2=pid_v2),
                    collection=collection,
                )
            if aop_pid:
                return cls.objects.get(
                    Q(aids__aop_pid=aop_pid) | Q(aids__pid_v2=aop_pid),
                    collection=collection,
                )

    @classmethod
    def get_or_create(
        cls,
        pid_v3,
        pid_v2=None,
        aop_pid=None,
        creator=None,
        issn_electronic=None,
        issn_print=None,
        issnl=None,
        volume=None,
        number=None,
        suppl=None,
        publication_year=None,
        collection=None,
    ):
        try:
            return cls.get(pid_v3, pid_v2, aop_pid, collection)
        except cls.DoesNotExist:
            obj = cls()
            obj.pid_v3 = pid_v3
            obj.created = datetime.utcnow()
            obj.creator = creator

            if collection:
                obj.save()
                obj.aids.add(
                    CollectionArticleId.create_or_update(
                        collection=collection,
                        pid_v3=pid_v3,
                        pid_v2=pid_v2,
                        aop_pid=aop_pid,
                        creator=creator,
                    )
                )

            if issn_electronic or issn_print or issnl:
                official_journal = OfficialJournal.get_or_create(
                    issn_print=issn_print,
                    issn_electronic=issn_electronic,
                    issnl=issnl,
                )
                obj.journal = Journal.get_or_create(official_journal)

                if volume or number or suppl or publication_year:
                    obj.issue = Issue.get_or_create(
                        official_journal=obj.journal.official_journal,
                        volume=volume,
                        supplement=suppl,
                        number=number,
                        publication_year=publication_year,
                        user=creator,
                    )
            obj.save()
            return obj

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

    def add_issue(
        self,
        official_journal=None,
        publication_year=None,
        volume=None,
        number=None,
        suppl=None,
        user=None,
    ):
        self.issue = Issue.get_or_create(
            official_journal,
            volume,
            suppl,
            number,
            publication_year,
            user,
        )

    def add_journal(
        self,
        official_journal=None,
        publication_year=None,
        volume=None,
        number=None,
        suppl=None,
        user=None,
    ):
        self.issue = Issue.get_or_create(
            official_journal,
            volume,
            suppl,
            number,
            publication_year,
            user,
        )

    autocomplete_search_field = "pid_v3"

    def autocomplete_label(self):
        return self.pid_v3

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

    def __str__(self):
        return f"{self.pid_v3}"

    class Meta:
        permissions = (
            (MAKE_ARTICLE_CHANGE, _("Can make article change")),
            (REQUEST_ARTICLE_CHANGE, _("Can request article change")),
        )

    base_form_class = ArticleForm


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
