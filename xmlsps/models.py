from django.db import models
from django.core.files.base import ContentFile

from core.models import CommonControlField


def xml_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    return f"xml_sps/{filename[0]}/{filename[1]}/{filename}"


class XMLSPS(CommonControlField):
    file = models.FileField(upload_to=xml_directory_path, null=True, blank=True)
    uri = models.URLField(null=True, blank=True)

    class Meta:
        ordering = ("file",)
        verbose_name = "XML SPS"
        verbose_name_plural = "XML SPS"

    def __str__(self):
        return f"{self.uri}"

    def save_file(self, name, content):
        self.file.save(name, ContentFile(content))
