from .. import tasks


"""
python manage.py runscript request_pid_for_new_website_docs \
    --script-args pids-tail.txt \
    "mongodb://192.168.1.19:27017/para_pid_provider" 1 website
"""
def run(pids_file_path, db_uri, user_id, files_storage_app_name):
    tasks.request_pid_for_new_website_docs.apply_async(
        args=(
            pids_file_path, db_uri, user_id, files_storage_app_name
        )
    )
