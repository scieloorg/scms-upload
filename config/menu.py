WAGTAIL_MENU_APPS_ORDER = [
    None,
    "upload",
    "processing",
    "Tarefas",
    "unexpected-error",
    "article",
    "issue",
    "journal",
    "collection",
    "migration",
    "pid_provider",
    "institution",
    "location",
    "researcher",
    "Configurações",
    "Relatórios",
    "Images",
    "Documentos",
    "Ajuda",
]


def get_menu_order(app_name):
    try:
        return WAGTAIL_MENU_APPS_ORDER.index(app_name)
    except:
        return 9000
