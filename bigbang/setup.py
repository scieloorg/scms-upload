import json

from django.contrib.auth import get_user_model

from collection.models import Collection, WebSiteConfiguration
from migration.models import ClassicWebsiteConfiguration
from files_storage.models import MinioConfiguration
from pid_requester.models import PidProviderConfig


User = get_user_model()


def setup(user, file_path):
    file_path = file_path or "./bigbang/.envs/.bigbang"
    with open(file_path) as fp:
        data = json.loads(fp.read())

    collection = Collection.get_or_create(acron=data["collection_acron"], user=user)

    config = data["classic_ws_config"]
    classic_website = ClassicWebsiteConfiguration.get_or_create(
        collection=collection,
        title_path=config["title_path"],
        issue_path=config["issue_path"],
        serial_path=config["SERIAL_PATH"],
        cisis_path=config.get("CISIS_PATH"),
        bases_work_path=config["BASES_WORK_PATH"],
        bases_pdf_path=config["BASES_PDF_PATH"],
        bases_translation_path=config["BASES_TRANSLATION_PATH"],
        bases_xml_path=config["BASES_XML_PATH"],
        htdocs_img_revistas_path=config["HTDOCS_IMG_REVISTAS_PATH"],
        user=user,
    )
    MinioConfiguration.get_or_create(user=user, **data["files_storage_config"])

    for item in data["websites"]:
        item["enabled"] = item["enabled"] == "true"
        WebSiteConfiguration.create_or_update(user=user, collection=collection, **item)
    PidProviderConfig.get_or_create(
        creator=user,
        pid_provider_api_post_xml=data["pid_provider"]["pid_provider"],
        pid_provider_api_get_token=data["pid_provider"]["token"],
        api_username=data["pid_provider"]["name"],
        api_password=data["pid_provider"]["pp"],
        timeout=10,
    )
