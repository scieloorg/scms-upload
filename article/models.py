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

