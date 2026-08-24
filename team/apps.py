from importlib import import_module

from django.apps import AppConfig


class TeamConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "team"

    def ready(self):
        import_module("team.signals").register_signals()
