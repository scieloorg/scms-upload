from bigbang.tasks import task_start


def run(username, status):

    task_start.apply_async(
        kwargs=dict(
            username=username,
            enable=(status == "true"),
        )
    )
