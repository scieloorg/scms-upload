from core.tasks import try_fetch_and_register_press_release

def run(username=None):
    try_fetch_and_register_press_release.apply_async(kwargs=dict(
        username=username,
    ))