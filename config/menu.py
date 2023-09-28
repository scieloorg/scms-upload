WAGTAIL_MENU_APPS_ORDER = {
    "collection": 400,
    "journal": 400,
    "issue": 400,
    "article": 400,
    "upload": 700,
    "migration": 700,
    "location": 800,
    "institution": 810,
    "pid_provider": 999,
}


def get_menu_order(app_name):
    return WAGTAIL_MENU_APPS_ORDER.get(app_name) or 900
