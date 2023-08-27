import logging
import os
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.core.files.base import ContentFile
from django.db import models
from django.utils.translation import gettext_lazy as _
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre
from packtools.utils import SPPackage

from core.models import CommonControlField


class OptimisedSPSPackageError(Exception):
    ...


def pkg_directory_path(instance, filename):
    subdir = "/".join(instance.sps_pkg_name.split("-"))
    return f"pkg/{subdir}/{filename}"


class SPSPkg(CommonControlField):
    sps_pkg_name = models.CharField(_("SPS Name"), max_length=32, null=True, blank=True)
    file = models.FileField(upload_to=pkg_directory_path, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["sps_pkg_name"]),
        ]

    @property
    def xml_with_pre(self):
        for item in XMLWithPre.create(path=self.file.path):
            return item

    def update_xml(self, xml_with_pre):
        with ZipFile(self.file.path, "a") as zf:
            zf.writestr(self.sps_pkg_name + ".xml", xml_with_pre.tostring())

    @classmethod
    def get(cls, sps_pkg_name):
        return cls.objects.get(sps_pkg_name=sps_pkg_name)

    @classmethod
    def get_or_create(cls, sps_pkg_name, tmp_sps_pkg_zip_path, user):
        try:
            obj = cls.get(sps_pkg_name)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.sps_pkg_name = sps_pkg_name
            obj.creator = user
        obj.save()

        obj.optimise_pkg(tmp_sps_pkg_zip_path)
        return obj

    def optimise_pkg(self, zip_file_path):
        try:
            with TemporaryDirectory() as targetdir:
                logging.info(f"Cria diretorio destino {targetdir}")

                with TemporaryDirectory() as workdir:
                    logging.info(f"Cria diretorio de trabalho {workdir}")

                    optimised_zip_sps_name = self.sps_pkg_name + ".zip"
                    target = os.path.join(targetdir, optimised_zip_sps_name)

                    package = SPPackage.from_file(zip_file_path, workdir)
                    package.optimise(new_package_file_path=target, preserve_files=False)

                with open(target, "rb") as fp:
                    logging.info(f"Save optimised package {optimised_zip_sps_name}")
                    self.file.save(optimised_zip_sps_name, ContentFile(fp.read()))
        except Exception as e:
            raise OptimisedSPSPackageError(
                _("Unable to build and add optimised sps package {}").format(
                    self.sps_pkg_name
                )
            )
