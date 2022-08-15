from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CommonControlField
from .forms import JournalForm


class Journal(CommonControlField):
    """
    Class that represent the SciELO Jounal
    """

    official_title = models.CharField(_('Official Title'), max_length=256, null=True, blank=True)
    foundation_year = models.CharField(_('Foundation Year'), max_length=4, null=True, blank=True)
    ISSN_print = models.CharField(_('ISSN Print'), max_length=9, null=True, blank=True)
    ISSN_electronic = models.CharField(_('ISSN Eletronic'), max_length=9, null=True, blank=True)
    ISSN_scielo = models.CharField(_('ISSN SciELO'), max_length=9, null=True, blank=True)
    ISSNL = models.CharField(_('ISSNL'), max_length=9, null=True, blank=True)

    base_form_class = JournalForm
