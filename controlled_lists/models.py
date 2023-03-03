from django.db import models
from django.utils.translation import gettext as _
from wagtail.admin.edit_handlers import FieldPanel
from wagtail.documents.edit_handlers import DocumentChooserPanel

from . import choices


class IndexedAt(models.Model):
    name = models.TextField(_("Name"), null=True, blank=False)
    acronym = models.TextField(_("Acronym"), null=True, blank=False)
    url = models.URLField(_("URL"), max_length=255, null=True, blank=False)
    description = models.TextField(_("Description"), null=True, blank=False)
    type = models.CharField(
        _("Type"),
        max_length=20,
        choices=choices.TYPE,
        null=True,
        blank=False
    )

    panels = [
        FieldPanel("name"),
        FieldPanel("acronym"),
        FieldPanel("url"),
        FieldPanel("description"),
        FieldPanel("type"),
    ]


class IndexedAtFile(models.Model):
    attachment = models.ForeignKey(
        "wagtaildocs.Document",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    is_valid = models.BooleanField(_("Is valid?"), default=False, blank=True, null=True)
    line_count = models.IntegerField(
        _("Number of lines"),
        default=0,
        blank=True,
        null=True
    )

    def filename(self):
        return os.path.basename(self.attachment.name)

    panels = [DocumentChooserPanel("attachment")]
