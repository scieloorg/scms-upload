import logging
import os

from django.utils.translation import gettext_lazy as _

from .models import (
    Configuration,
    MinioFile,
)
from .minio import MinioStorage
from . import exceptions


def get_files_storage(files_storage_config):
    try:
        return MinioStorage(
            minio_host=files_storage_config.host,
            minio_access_key=files_storage_config.access_key,
            minio_secret_key=files_storage_config.secret_key,
            bucket_root=files_storage_config.bucket_root,
            bucket_subdir=files_storage_config.bucket_app_subdir,
            minio_secure=files_storage_config.secure,
            minio_http_client=None,
        )
    except Exception as e:
        raise exceptions.GetFilesStorageError(
            _("Unable to get MinioStorage {} {} {}").format(
                files_storage_config, type(e), e)
        )


class FilesStorageManager:

    def __init__(self, files_storage_name):
        self.config = Configuration.get_or_create(name=files_storage_name)
        self.files_storage = get_files_storage(self.config)

    def fput_content(self, latest, filename, content, creator):
        finger_print = MinioFile.generate_finger_print(content)
        if latest and finger_print == latest.finger_print:
            return
        name, extension = os.path.splitext(filename)
        if extension == '.xml':
            mimetype = "text/xml"

        object_name=f"{name}/{finger_print}.{extension}"
        uri = self.files_storage.fput_content(
            content,
            mimetype=mimetype,
            object_name=f"{self.config.bucket_app_subdir}/{object_name}",
        )
        logging.info(uri)
        return MinioFile.create(creator, uri, filename, finger_print)

    def register(self, source_filename, subdirs, preserve_name):
        return self.files_storage.register(
            source_filename,
            subdirs=os.path.join(self.config.bucket_app_subdir, subdirs),
            preserve_name=preserve_name,
        )
