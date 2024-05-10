import json

from django.contrib.auth import get_user_model

from collection.models import Collection, WebSiteConfiguration
from files_storage.models import MinioConfiguration
from migration.models import ClassicWebsiteConfiguration
from pid_provider.models import PidProviderConfig

User = get_user_model()


def setup(user, file_path=None, config=None):

    if config:
        data = config
    else:
        try:
            file_path = file_path or "./bigbang/.envs/.bigbang"
            with open(file_path) as fp:
                data = json.loads(fp.read())
        except FileNotFoundError:
            raise FileNotFoundError(file_path)

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
        WebSiteConfiguration.create_or_update(
            user=user,
            collection=collection,
            url=item.get("url"),
            purpose=item.get("purpose"),
            api_url_article=item.get("api_url_article"),
            api_url_issue=item.get("api_url_issue"),
            api_url_journal=item.get("api_url_journal"),
            api_url=item.get("api_url"),
            api_get_token_url=item.get("api_get_token_url"),
            api_username=item.get("api_username"),
            api_password=item.get("api_password"),
            enabled=item.get("enabled"),
        )
    PidProviderConfig.get_or_create(
        creator=user,
        pid_provider_api_post_xml=data["pid_provider"]["pid_provider"],
        pid_provider_api_get_token=data["pid_provider"]["token"],
        api_username=data["pid_provider"]["name"],
        api_password=data["pid_provider"]["pp"],
        timeout=10,
    )
