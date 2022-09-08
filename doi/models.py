from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CommonControlField


class DOIWithLang(CommonControlField):
    doi = models.CharField(_('DOI'), max_length=255, blank=False, null=False)
    lang = models.CharField(_('Language'), max_length=64, blank=False, null=False)

    def __str__(self):
        return f'{self.lang.upper()}: {self.doi}'
