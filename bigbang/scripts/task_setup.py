from bigbang.tasks import task_setup


def run(username, file_path=None, config=None):

    task_setup.apply_async(
        kwargs=dict(
            username=username,
            file_path=file_path,
            config=config
        )
    )
