from pid_requester.tasks import request_pid_for_file


def run(username, file_path):
    request_pid_for_file.apply_async(
        kwargs={
            "username": username,
            "file_path": file_path,
        }
    )
