from core.tasks import try_fetch_and_register_press_release

def run(journal_acronym=None, pressrelease_lang=None, username=None):
    try_fetch_and_register_press_release.apply_async(kwargs=dict(
        journal_acronym=journal_acronym,
        pressrelease_lang=pressrelease_lang,
        username=username,
    ))