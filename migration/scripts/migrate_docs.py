from migration.tasks import task_create_articles


def run(username, collection_acron, from_date, force_update):
    force_update = bool(force_update == 'true')
    task_create_articles.apply_async(
        args=(username, collection_acron, from_date, force_update)
    )
