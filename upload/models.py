from django.db import models
from django.utils.translation import gettext_lazy as _

from wagtail.admin.edit_handlers import FieldPanel

from core.models import CommonControlField

from .permission_helper import (ACCEPT, ENQUEUE_FOR_VALIDATION, REJECT, PREVIEW, SCHEDULE_FOR_PUBLICATION)
from .choices import PackageStatus
from .forms import UploadPackageForm


class Package(CommonControlField):
    file = models.FileField(_('Package File'), null=True, blank=True)
    signature = models.CharField(_('Signature'), max_length=32, null=True, blank=True)
    status = models.PositiveSmallIntegerField(_('Status'), choices=PackageStatus.choices, default=PackageStatus.SUBMITTED)

    panels = [
        FieldPanel('file'),
    ]

    def __str__(self):
        return self.file.name

    def current_status(self):
        return PackageStatus.choices[self.status - 1][1]
    
    base_form_class = UploadPackageForm

    class Meta:
        permissions = (
            (ACCEPT, _("Can accept")),
            (ENQUEUE_FOR_VALIDATION, _("Can enqueue for validation")),
            (REJECT, _("Can reject")),
            (PREVIEW, _("Can preview")),
            (SCHEDULE_FOR_PUBLICATION, _("Can schedule for publication")),
        )
