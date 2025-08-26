from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel

from core.models import CommonControlField

from .forms import DOIWithLangForm
from collection.models import Language


class DOIWithLang(CommonControlField):
    doi = models.CharField(_("DOI"), max_length=256, blank=False, null=False)
    lang = models.ForeignKey(
        Language, null=True, blank=True, on_delete=models.SET_NULL
    )

    panels = [
        FieldPanel("doi"),
        FieldPanel("lang"),
    ]

    def __str__(self):
        return f"{self.lang}: {self.doi}"

    base_form_class = DOIWithLangForm


class XMLCrossRef(CommonControlField):
    file = models.FileField(null=True, blank=True)
    uri = models.URLField(null=True, blank=True)

    class Meta:
        ordering = ("file",)
        verbose_name = "XMLCrossRef"
        verbose_name_plural = "XMLCrossRef"

    def __str__(self):
        return f"{self.uri}"
