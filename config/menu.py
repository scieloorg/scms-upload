WAGTAIL_MENU_APPS_ORDER = [
    "Tarefas",
    "unexpected-error",
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
]


def get_menu_order(app_name):
    try:
        return WAGTAIL_MENU_APPS_ORDER.index(app_name) + 1
    except:
        return 9000
