
WAGTAIL_MENU_APPS_ORDER = [
    "collection",
    "pid_provider",
    "migration",
    "processing",
    "Tarefas",
    "journal",
    "issue",
    "institution",
    "article",
    "researcher",
    "location",
    "unexpected-error",
    "Configurações",
    "Relatórios",
    "Ajuda",
    "Images",
    "Documentos",
]

def get_menu_order(app_name):
    try:
        return WAGTAIL_MENU_APPS_ORDER.index(app_name) + 1
    except:
        return 9000

