from django.db import models
from django.utils.translation import gettext_lazy as _

from wagtail.admin.edit_handlers import FieldPanel

from core.models import CommonControlField

from .permission_helper import FINISH_DEPOSIT
from .choices import (PackageStatus, VALIDATION_ERROR_CATEGORY, VALIDATION_ERROR_SEVERITY,)
from .forms import UploadPackageForm
from .tasks import get_files_list


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

    def files_list(self):
        return {'files': get_files_list(self.file)}

    base_form_class = UploadPackageForm

    class Meta:
        permissions = (
            (FINISH_DEPOSIT, _("Can finish deposit")),
        )


class ValidationError(models.Model):
    category = models.CharField(_('Category'), max_length=128, choices=VALIDATION_ERROR_CATEGORY, null=False, blank=False)
    severity = models.CharField(_('Severity'), max_length=128, choices=VALIDATION_ERROR_SEVERITY, null=False, blank=False)
    
    position = models.PositiveIntegerField(_('Position'), null=True, blank=True)
    snippet = models.TextField(_('Affected snippet'), max_length=10240, null=True, blank=True)

    package = models.ForeignKey('Package', on_delete=models.CASCADE, null=False, blank=False)   

    # TODO: terá uma chave estrageira para um novo modelo chamado ValidationFeedback
    
    panels = [
        MultiFieldPanel(
            [
                FieldPanel('package'),
                FieldPanel('category'),
                FieldPanel('severity'),
                FieldPanel('position'),
            ],
            heading=_('Identification'),
            classname='collapsible'
        ),
        MultiFieldPanel(
            [
                FieldPanel('snippet'),
            ],
            heading=_('Content'),
            classname='collapsible'
        )
    ]
