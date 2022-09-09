from django.db import models
from django.utils.translation import gettext_lazy as _

from modelcluster.fields import ParentalKey
from wagtail.admin.edit_handlers import InlinePanel, FieldPanel, MultiFieldPanel
from wagtail.core.models import Orderable, ClusterableModel

from core.models import CommonControlField
from doi.models import DOIWithLang
from issue.models import Issue
from journal.models import OfficialJournal
from researcher.models import Researcher

from .forms import ArticleForm, RelatedItemForm

from . import choices


class Article(ClusterableModel, CommonControlField):
    # Identifiers
    pid_v3 = models.CharField(_('PID v3'), max_length=23, blank=True, null=True)

    # FIXME: remover assim que forem contemplados por SciELODocument
    pid_v2 = models.CharField(_('PID v2'), max_length=23, blank=True, null=True)
    aop_pid = models.CharField(_('AOP PID'), max_length=23, blank=True, null=True)

    # Article type
    article_type = models.CharField(_('Article type'), max_length=32, choices=choices.ARTICLE_TYPE, blank=False, null=False)

    # Page
    elocation_id = models.CharField(_('Elocation ID'), max_length=64, blank=True, null=True)
    fpage = models.CharField(_('First page'), max_length=16, blank=True, null=True)
    lpage = models.CharField(_('Last page'), max_length=16, blank=True, null=True)

    # External models
    journal = models.ForeignKey(OfficialJournal, blank=True, null=True, on_delete=models.SET_NULL)
    issue = models.ForeignKey(Issue, blank=True, null=True, on_delete=models.CASCADE)

    related_items = models.ManyToManyField('self', symmetrical=False, through='RelatedItem', related_name='related_to')

    panel_article_ids = MultiFieldPanel(heading='Article identifiers', classname='collapsible')
    panel_article_ids.children = [
        FieldPanel('pid_v2'),
        FieldPanel('pid_v3'),
        FieldPanel('aop_pid'),
        InlinePanel(relation_name='doi_with_lang', label='DOI with Language'),
    ]

    panel_article_details = MultiFieldPanel(heading='Article details', classname='collapsible')
    panel_article_details.children = [
        FieldPanel('article_type'),
        InlinePanel(relation_name='title_with_lang', label='Title with Language'),
        InlinePanel(relation_name='author', label='Authors'),
        FieldPanel('elocation_id'),
        FieldPanel('fpage'),
        FieldPanel('lpage'),
    ]
    
    panels = [
        panel_article_ids,
        panel_article_details,
        FieldPanel('journal', classname='collapsible'),
        FieldPanel('issue', classname='collapsible'),
    ]

    def __str__(self):
        return f'{self.pid_v3 or self.pid_v2 or self.aop_pid or self.id}'

    base_form_class = ArticleForm


class ArticleAuthor(Orderable, Researcher):
    author = ParentalKey('Article', on_delete=models.CASCADE, related_name='author')


class ArticleDOIWithLang(Orderable, DOIWithLang):
    doi_with_lang = ParentalKey('Article', on_delete=models.CASCADE, related_name='doi_with_lang')


class Title(CommonControlField):
    title = models.CharField(_('Title'), max_length=255, blank=False, null=False)
    lang = models.CharField(_('Language'), max_length=64, blank=False, null=False)

    panels = [
        FieldPanel('title'),
        FieldPanel('lang'),
    ]

    def __str__(self):
        return f'{self.lang.upper()}: {self.title}'

    class Meta:
        abstract = True


class ArticleTitle(Orderable, Title):
    title_with_lang = ParentalKey('Article', on_delete=models.CASCADE, related_name='title_with_lang')


class RelatedItem(CommonControlField):
    item_type = models.CharField(_('Related item type'), max_length=32, choices=choices.RELATED_ITEM_TYPE, blank=False, null=False)
    source_article = models.ForeignKey('Article', related_name='source_article', on_delete=models.CASCADE, null=False, blank=False)
    target_article = models.ForeignKey('Article', related_name='target_article', on_delete=models.CASCADE, null=False, blank=False)

    panel = [
        FieldPanel('item_type'),
        FieldPanel('source_article'),
        FieldPanel('target_article'),
    ]

    def __str__(self):
        return f'{self.source_article} - {self.target_article} ({self.item_type})'

    base_form_class = RelatedItemForm
