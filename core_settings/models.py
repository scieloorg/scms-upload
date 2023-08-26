from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.contrib.settings.models import BaseSetting, register_setting


@register_setting
class CustomSettings(BaseSetting):
    """
    This a settings model.

    More about look:
        https://docs.wagtail.org/en/stable/reference/contrib/settings.html
    """

    favicon = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    admin_logo = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    panels = [
        FieldPanel("favicon"),
        FieldPanel("admin_logo"),
    ]
