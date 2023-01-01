import json

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from .models import (
    Collection,
    ClassicWebsiteConfiguration,
    NewWebSiteConfiguration,
)
from files_storage.models import Configuration as FilesStorageConfiguration
from .. import exceptions


User = get_user_model()


def load_config(user):
    try:
        with open(".envs/.bigbang") as fp:
            data = json.loads(fp.read())

        collection = Collection.get_or_create(
            data['collection_acron'],
            user,
            data['collection_name'],
        )
        classic_website = ClassicWebsiteConfiguration.get_or_create(
            collection, data['classic_ws_config'], user,
        )
        for fs_data in data['files_storages']:
            fs_data['user'] = user
            fs_config = FilesStorageConfiguration.get_or_create(
                **fs_data
            )
        new_website_config = NewWebSiteConfiguration.get_or_create(
            data['url'], data['db_uri'], user)
    except Exception as e:
        raise exceptions.StartCollectionConfigurationError(
            _("Unable to start system %s") % e)


def run(user_id=None):
    user = User.objects.first()
    load_config(user)
