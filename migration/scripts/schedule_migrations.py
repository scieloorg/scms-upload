from .. import tasks


def run(user_id):
    tasks.start.apply_async(args=(user_id, ))
