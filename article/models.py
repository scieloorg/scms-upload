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
