import json

from django.contrib.auth import get_user_model

from collection.models import Collection
from migration.models import (
    ClassicWebsiteConfiguration,
)

User = get_user_model()


def load_classic_website_configuration(username):
    user = User.objects.get(username=username)
    with open(".envs/.bigbang") as fp:
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


def run(username):
    load_classic_website_configuration(username)
