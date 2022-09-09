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
    pid_v2 = models.CharField(_('PID v2'), max_length=23, blank=True, null=True)
    aop_pid = models.CharField(_('AOP PID'), max_length=23, blank=True, null=True)

    # Page
    elocation_id = models.CharField(_('Elocation ID'), max_length=64, blank=True, null=True)
    fpage = models.CharField(_('First page'), max_length=16, blank=True, null=True)
    lpage = models.CharField(_('Last page'), max_length=16, blank=True, null=True)

    # External models
    journal = models.ForeignKey(OfficialJournal, blank=True, null=True, on_delete=models.SET_NULL)
    issue = models.ForeignKey(Issue, blank=True, null=True, on_delete=models.CASCADE)

    panel_doc_ids = MultiFieldPanel(heading='Document identifiers', classname='collapsible')
    panel_doc_ids.children = [
        FieldPanel('pid_v2'),
        FieldPanel('pid_v3'),
        FieldPanel('aop_pid'),
        InlinePanel(relation_name='doi_with_lang', label='DOI with Language'),
    ]

    panel_doc_details = MultiFieldPanel(heading='Document details', classname='collapsible')
    panel_doc_details.children = [
        InlinePanel(relation_name='title_with_lang', label='Title with Language'),
        InlinePanel(relation_name='author', label='Authors'),
        FieldPanel('elocation_id'),
        FieldPanel('fpage'),
        FieldPanel('lpage'),
    ]
    
    panels = [
        panel_doc_ids,
        panel_doc_details,
        FieldPanel('journal', classname='collapsible'),
        FieldPanel('issue', classname='collapsible'),
        InlinePanel(relation_name='related_item', label='Related item', classname='collapsible'),
    ]

    def __str__(self):
        return self.pid_v2

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
    item_type = models.CharField(_('Related item type'), max_length=128, null=False, blank=False) 

    panel = [
        FieldPanel('item_type'),
    ]

    def __str__(self):
        return self.item_type

    class Meta:
        abstract = True


class ArticleRelatedItem(Orderable, RelatedItem):
    related_item = ParentalKey('Article', on_delete=models.CASCADE, related_name='related_item')
