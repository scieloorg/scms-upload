import json
import logging

from django.utils.translation import gettext_lazy as _

from . import exceptions
from migration.models import (
    ClassicWebsiteConfiguration,
)
from .models import (
    Collection,
    FilesStorageConfiguration,
    NewWebSiteConfiguration,
)


def start():
    try:
        with open(".envs/.bigbang") as fp:
            data = json.loads(fp.read())
        user_id = 1
        collection = Collection.get_or_create(acron=data["collection_acron"])
        try:
            classic_website = ClassicWebsiteConfiguration.objects.get(
                collection=collection
            )
        except ClassicWebsiteConfiguration.DoesNotExist:
            classic_website = ClassicWebsiteConfiguration()
            classic_website.collection = collection
            classic_website.title_path = data["classic_ws_config"]["title_path"]
            classic_website.issue_path = data["classic_ws_config"]["issue_path"]
            classic_website.serial_path = data["classic_ws_config"]["SERIAL_PATH"]
            classic_website.cisis_path = data["classic_ws_config"].get("CISIS_PATH")
            classic_website.bases_work_path = data["classic_ws_config"][
                "BASES_WORK_PATH"
            ]
            classic_website.bases_pdf_path = data["classic_ws_config"]["BASES_PDF_PATH"]
            classic_website.bases_translation_path = data["classic_ws_config"][
                "BASES_TRANSLATION_PATH"
            ]
            classic_website.bases_xml_path = data["classic_ws_config"]["BASES_XML_PATH"]
            classic_website.htdocs_img_revistas_path = data["classic_ws_config"][
                "HTDOCS_IMG_REVISTAS_PATH"
            ]
            classic_website.creator_id = user_id
            classic_website.save()
        try:
            files_storage_config = FilesStorageConfiguration.objects.get(
                host=data["files_storage_config"]["host"]
            )
        except FilesStorageConfiguration.DoesNotExist:
            files_storage_config = FilesStorageConfiguration()
            files_storage_config.host = data["files_storage_config"]["host"]
            files_storage_config.access_key = data["files_storage_config"]["access_key"]
            files_storage_config.secret_key = data["files_storage_config"]["secret_key"]
            files_storage_config.secure = (
                data["files_storage_config"]["secure"] == "true"
            )
            files_storage_config.bucket_public_subdir = data["files_storage_config"][
                "bucket_public_subdir"
            ]
            files_storage_config.bucket_migration_subdir = data["files_storage_config"][
                "bucket_migration_subdir"
            ]
            files_storage_config.bucket_root = data["files_storage_config"][
                "bucket_root"
            ]
            files_storage_config.creator_id = user_id
            files_storage_config.save()
        try:
            new_website_config = NewWebSiteConfiguration.objects.get(url=data["url"])
        except NewWebSiteConfiguration.DoesNotExist:
            new_website_config = NewWebSiteConfiguration()
            new_website_config.db_uri = data["db_uri"]
            new_website_config.url = data.get("url")
            new_website_config.creator_id = user_id
            new_website_config.save()

        return (
            classic_website,
            files_storage_config,
            new_website_config,
        )
    except Exception as e:
        raise exceptions.StartCollectionConfigurationError(
            "Unable to start system %s" % e
        )
