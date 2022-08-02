from django.db import models
from django.utils.translation import gettext as _


class PackageStatus(models.TextChoices):
    SUBMITTED = 1, _('Submitted')
    FINISHED = 2, _('Finished')
