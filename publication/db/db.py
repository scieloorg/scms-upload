import logging
from datetime import datetime
from pymongo import MongoClient

from mongoengine import connect, register_connection
from tenacity import retry, stop_after_attempt, wait_exponential

from publication.db import exceptions


class PublicationGetObjectError(Exception):
    ...


class PublicationSaveObjectError(Exception):
    ...


def mk_connection(host, alias=None):
    try:
        return _db_connect_by_uri(host, alias)
    except Exception as e:
        raise exceptions.DBConnectError(str({"exception": type(e), "msg": str(e)}))


@retry(wait=wait_exponential(), stop=stop_after_attempt(10))
def _db_connect_by_uri(uri, alias=None):
    """
    mongodb://{login}:{password}@{host}:{port}/{database}
    """
    params = {"host": uri, "maxPoolSize": None}
    if alias:
        params["alias"] = alias
    conn = connect(**params)
    print("%s connected" % params)
    return conn


class Publication:
    def __init__(self, website, model):
        self.website = website
        self.model = model
        self.c = MongoClient(website.db_uri)

    def get_object(self, **kwargs):
        logging.info(
            f"Publication.get_object {self.model} {self.website} {self.website.db_uri} {self.website.db_name}"
        )
        try:
            item = self.model.objects.get(**kwargs)
        except self.model.DoesNotExist:
            item = self.model()
        except Exception as e:
            logging.exception(e)
            raise PublicationGetObjectError(f"Unable to get object {kwargs}")
        return item

    def save_object(self, obj):
        try:
            if not hasattr(obj, "created"):
                obj.created = None

            obj.updated = datetime.utcnow()
            if not obj.created:
                obj.created = obj.updated

            obj.save()
            return obj
        except Exception as e:
            logging.info(f"save_object...")
            logging.exception(e)
            raise PublicationSaveObjectError(f"Unable to save object {obj}")
