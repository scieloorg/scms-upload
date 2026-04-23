WAGTAIL_MENU_APPS_ORDER = [
    None,
    "unexpected-error",
    "Tasks",
    "processing",
    "migration",
    "journal",
    "issue",
    "article",
    "institution",
    "location",
    "researcher",
    "collection",
    "pid_provider",
    "Configurações",
    "Relatórios",
    "Images",
    "Documentos",
    "Ajuda",
    "upload",
    "upload-error",
]


def get_menu_order(app_name):
    try:
        return WAGTAIL_MENU_APPS_ORDER.index(app_name)
    except:
        return 9000
