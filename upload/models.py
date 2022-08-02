from django.db import models
from django.utils.translation import gettext_lazy as _

from wagtail.admin.edit_handlers import FieldPanel

from core.models import CommonControlField

from .permission_helper import FINISH_DEPOSIT
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
        return self.file

    def current_status(self):
        return PackageStatus.choices[self.status - 1][1]
    
    base_form_class = UploadPackageForm

    class Meta:
        permissions = (
            (FINISH_DEPOSIT, _("Can finish deposit")),
        )
