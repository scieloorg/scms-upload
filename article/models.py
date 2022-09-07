from django.db import models
from django.utils.translation import gettext_lazy as _

from modelcluster.fields import ParentalKey
from wagtail.admin.edit_handlers import InlinePanel, FieldPanel, MultiFieldPanel
from wagtail.core.models import Orderable, ClusterableModel

from core.models import CommonControlField
from journal.models import OfficialJournal

from .forms import ArticleForm


class Article(ClusterableModel, CommonControlField):
    # Identifiers
    pid_v3 = models.CharField(_('PID v3'), max_length=23, blank=True, null=True)
    pid_v2 = models.CharField(_('PID v2'), primary_key=True, max_length=23, blank=False, null=False)
    aop_pid = models.CharField(_('AOP PID'), max_length=23, blank=True, null=True)

    # Year of publication
    pub_year = models.IntegerField(_('Publication year'), blank=True, null=True)

    # Issue
    volume = models.CharField(_('Volume'), max_length=32, blank=True, null=True)
    number = models.CharField(_('Number'), max_length=16, blank=True, null=True)
    suppl = models.CharField(_('Supplement'), max_length=32, blank=True, null=True)

    # Page
    elocation_id = models.CharField(_('Elocation ID'), max_length=64, blank=True, null=True)
    fpage = models.CharField(_('First page'), max_length=16, blank=True, null=True)
    lpage = models.CharField(_('Last page'), max_length=16, blank=True, null=True)

    journal = models.ForeignKey(OfficialJournal, blank=True, null=True, on_delete=models.SET_NULL)

    base_form_class = ArticleForm

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
    ]

    panel_issue = MultiFieldPanel(heading='Issue', classname='collapsible')
    panel_issue.children = [
        FieldPanel('pub_year'),
        FieldPanel('volume'),
        FieldPanel('number'),
        FieldPanel('suppl'),
    ]

    panel_page = MultiFieldPanel(heading='Page', classname='collapsible')
    panel_page.children = [
        FieldPanel('elocation_id'),
        FieldPanel('fpage'),
        FieldPanel('lpage'),
    ]
    
    panels = [
        panel_doc_ids,
        panel_doc_details,
        InlinePanel(relation_name='related_item', label='Related item', classname='collapsible'),
        FieldPanel('journal', classname='collapsible'),
        panel_issue,
        panel_page,
    ]

    def __str__(self):
        return self.pid_v2


class Author(models.Model):
    first_name = models.CharField(_('First name'), max_length=128, blank=False, null=False)
    surname = models.CharField(_('Surname'), max_length=128, blank=False, null=False)

    panels = [
        FieldPanel('first_name'),
        FieldPanel('surname'),
    ]

    def __str__(self):
        return f'{self.first_name} {self.surname.upper()}'

    class Meta:
        abstract = True


class ArticleAuthor(Orderable, Author):
    author = ParentalKey('Article', on_delete=models.CASCADE, related_name='author')


class DOIWithLang(models.Model):
    doi = models.CharField(_('DOI'), max_length=255, blank=False, null=False)
    lang = models.CharField(_('Language'), max_length=64, blank=False, null=False)

    panels = [
        FieldPanel('doi'),
        FieldPanel('lang'),
    ]

    def __str__(self):
        return f'{self.lang.upper()}: {self.doi}'

    class Meta:
        abstract = True


class ArticleDOIWithLang(Orderable, DOIWithLang):
    doi_with_lang = ParentalKey('Article', on_delete=models.CASCADE, related_name='doi_with_lang')


class Title(models.Model):
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


