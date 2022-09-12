from datetime import datetime

from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
)
from mongoengine import (
    connect,
)

from libs.dsm import exceptions

import os


OPAC_STRING_CONNECTION = os.environ.get('OPAC_STRING_CONNECTION', '')


def mk_connection(host=OPAC_STRING_CONNECTION, alias=None):
    try:
        return _db_connect_by_uri(host, alias)
    except Exception as e:
        raise exceptions.DBConnectError(
            str({"exception": type(e), "msg": str(e)})
        )


@retry(wait=wait_exponential(), stop=stop_after_attempt(10))
def _db_connect_by_uri(uri, alias=None):
    """
    mongodb://{login}:{password}@{host}:{port}/{database}
    """
    params = {"host": uri, "maxPoolSize": None}
    if alias:
        params['alias'] = alias
    conn = connect(**params)
    print("%s connected" % params)
    return conn


def save_data(model):
    if not hasattr(model, 'created'):
        model.created = None

    model.updated = datetime.utcnow()
    if not model.created:
        model.created = model.updated

    model.save()
    return model
