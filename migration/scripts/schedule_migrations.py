from migration.tasks import task_schedule_migrations


def run(username, collection_acron=None):
    task_schedule_migrations.apply_async(
        args=(username, collection_acron)
    )
