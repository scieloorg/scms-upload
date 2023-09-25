from bigbang.tasks import task_start


def run(username, file_path=None, activate_run_all=None, activate_run_partial=None):
    task_start.apply_async(
        kwargs=dict(
            username=username,
            file_path=file_path,
            activate_run_all=activate_run_all == 'true',
            activate_run_partial=activate_run_partial == 'true',
        ))
