from .models import (
    MigrationFailure,
)


def register_failure(action_name, object_name, pid, e, user):
    migration_failure = MigrationFailure()
    migration_failure.action_name = action_name
    migration_failure.object_name = object_name
    migration_failure.pid = pid
    migration_failure.exception_msg = str(e)
    migration_failure.exception_type = str(type(e))
    migration_failure.creator = user
    migration_failure.save()
