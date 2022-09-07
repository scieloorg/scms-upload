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
