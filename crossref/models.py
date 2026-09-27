from django.core.files.base import ContentFile
from django.db import models
from lxml import etree as ET

from core.models import CommonControlField
from article.models import Article



def migrated_files_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>

    return f"migration/{instance.collection.acron}/{instance.original_path}"

# Create your models here.
class XMLCrossRef(CommonControlField):
    file = models.FileField(
        upload_to=migrated_files_directory_path, null=True, blank=True
    )
    article = models.ForeignKey(
        Article,
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.SET_NULL,
    )

    @classmethod
    def create(cls, user, article):
        obj = cls()
        obj.article = article
        obj.creator = user
        obj.save()
        return obj

    def generateXML(self):
        xml_tree = self.article.sps_pkg.xml_with_pre.xmltree
        xml_crossref = ET.ElementTree(crossref.pipeline_crossref(xml_tree, data))
        xml_string = ET.tostring(xml_crossref, encoding="utf-8", pretty_print=True)
        self.save_file(self.article.sps_pkg.sps_pkg_name+".xml", xml_string)

    def save_file(self, name, content):
        if self.file:
            try:
                self.file.delete(save=True)
            except Exception as e:
                pass
        self.file.save(name, ContentFile(content))