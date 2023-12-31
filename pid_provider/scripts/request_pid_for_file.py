from pid_provider.tasks import provide_pid_for_file


def run(username, file_path):
    provide_pid_for_file.apply_async(
        kwargs={
            "username": username,
            "file_path": file_path,
        }
    )
