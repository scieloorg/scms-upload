from .. import tasks


def run(pids_file_path, db_uri, user_id, files_storage_app_name):
    tasks.request_pid_for_new_website_docs.apply_async(
        args=(
            pids_file_path, db_uri, user_id, files_storage_app_name
        )
    )
