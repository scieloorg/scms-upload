from django.db import models
from django.utils.translation import gettext_lazy as _

from modelcluster.fields import ParentalKey
from wagtail.admin.edit_handlers import FieldPanel, InlinePanel
from wagtail.core.models import Orderable, ClusterableModel

from core.models import CommonControlField, RichTextField

from . import choices, forms


class ManualChecking(ClusterableModel, CommonControlField):
    title = models.CharField(_('Title'), max_length=255, blank=True, null=True)
    validation_group = models.CharField(_('Validation group'), max_length=255, blank=True, null=True)
    comment = RichTextField(_('Comment'), max_length=512, blank=True, null=True)
    version = models.IntegerField(_('Version number'), blank=False, null=False)
    status = models.CharField(_('Status'), max_length=32, choices=choices.MANUAL_CHECKING_STATUS, default=choices.MC_STATUS_ENABLED)

    panels = [
        FieldPanel('title', classname='collapsible'),
        FieldPanel('validation_group', classname='collapsible'),
        FieldPanel('comment', classname='collapsible'),
        FieldPanel('version', classname='collapsible'),
        FieldPanel('status', classname='collapsible'),
        InlinePanel(relation_name='item', label='Checklist Items', classname='collapsible'),
    ]

    def __str__(self):
        return f'{self.title or ""} - {self.validation_group or ""} ({self.status})'

    base_form_class = forms.ManualCheckingForm


class Item(CommonControlField):
    name = models.CharField(_('Name'), max_length=128, blank=False, null=False)
    description = models.CharField(_('Description'), max_length=512, blank=False, null=False)
    response = models.BooleanField(_('Response'), null=True, blank=True)

    panels = [
        FieldPanel('name'),
        FieldPanel('description'),
        FieldPanel('response'),
    ]

    def __str__(self):
        return self.name

    base_form_class = forms.ItemForm


class ManualCheckingItem(Orderable, Item):
    item = ParentalKey('ManualChecking', on_delete=models.CASCADE, related_name='item')
