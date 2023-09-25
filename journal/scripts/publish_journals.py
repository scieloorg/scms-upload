from journal.tasks import task_publish_journals


def run(username, website_kind=None, collection_acron=None):
    task_publish_journals.apply_async(
        args=(username, website_kind, collection_acron)
    )
