from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CommonControlField


class Collection(CommonControlField):
    """
    Class that represent the Collection
    """

    def __unicode__(self):
        return u'%s' % self.name

    def __str__(self):
        return u'%s' % self.name

    name = models.CharField(_('Collection Name'), max_length=255, null=False, blank=False)
