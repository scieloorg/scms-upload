from django.db import models

from core.models import CommonControlField


class XMLSPS(CommonControlField):
    file = models.FileField(null=True, blank=True)
    uri = models.URLField(null=True, blank=True)
    pid = models.CharField(max_length=23, null=True, blank=True)

    class Meta:
        ordering = ("file",)
        verbose_name = "XML SPS"
        verbose_name_plural = "XML SPS"

    def __str__(self):
        return f"{self.uri}"
