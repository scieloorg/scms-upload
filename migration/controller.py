import logging
import traceback
import sys

from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model

from .models import (
    MigrationFailure,
)

User = get_user_model()


def _register_failure(msg,
                      collection_acron, action_name, object_name, pid,
                      e, exc_type, exc_value, exc_traceback,
                      user_id):
    exc_type, exc_value, exc_traceback = sys.exc_info()
    logging.error(_("{} {} {}").format(msg, collection_acron, pid))
    logging.exception(e)
    register_failure(
        collection_acron, action_name, object_name, pid, e,
        exc_type, exc_value, exc_traceback, user_id,
    )


def register_failure(collection_acron, action_name, object_name, pid, e,
                     exc_type, exc_value, exc_traceback, user_id):
    migration_failure = MigrationFailure()
    migration_failure.collection_acron = collection_acron
    migration_failure.action_name = action_name
    migration_failure.object_name = object_name
    migration_failure.pid = pid[:23]
    migration_failure.exception_msg = str(e)[:555]
    migration_failure.traceback = [
        str(item)
        for item in traceback.extract_tb(exc_traceback)
    ]
    migration_failure.exception_type = str(type(e))
    migration_failure.creator = User.objects.get(pk=user_id)
    migration_failure.save()
