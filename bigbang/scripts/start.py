from bigbang.tasks import task_start


def run(username, file_path, status):

    task_start.apply_async(
        kwargs=dict(
            username=username,
            file_path=file_path,
            enable=(status == "true"),
        )
    )
