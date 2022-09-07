from django.db import models
from django.utils.translation import gettext_lazy as _

from modelcluster.fields import ParentalKey
from wagtail.admin.edit_handlers import InlinePanel, FieldPanel, MultiFieldPanel
from wagtail.core.models import Orderable, ClusterableModel

from core.models import CommonControlField
from journal.models import OfficialJournal

from .forms import ArticleForm


class Article(ClusterableModel, CommonControlField):
