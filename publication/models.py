from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CommonControlField
from libs.xml_sps_utils import get_xml_with_pre_from_uri
from . import choices

User = get_user_model()


class PublicationArticle(CommonControlField):

    v3 = models.CharField(_('PID v3'), max_length=23, blank=True, null=True)
    xml_uri = models.CharField(_('XML URI'), max_length=256, blank=True, null=True)
    status = models.CharField(
        _('Publication status'), max_length=20,
        blank=True, null=True, choices=choices.PUBLICATION_STATUS)

    @classmethod
    def get_or_create(cls, v3, creator):
        try:
            return cls.objects.get(v3=v3)
        except cls.DoesNotExist:
            item = cls()
            item.v3 = v3
            item.creator = creator
            item.created = datetime.utcnow()
            item.save()
            return item

    @property
    def xml_with_pre(self):
        return get_xml_with_pre_from_uri(self.xml_uri)
