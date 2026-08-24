from team.constants import TeamGroups
from upload.permissions import (
    ACCESS_ALL_PACKAGES,
    ASSIGN_PACKAGE,
    FINISH_DEPOSIT,
    PUBLISH_PACKAGE,
    REPUBLISH_PACKAGE,
)

CRUD_ACTIONS = ("add", "change", "delete", "view")
VIEW_ACTIONS = ("view",)
FULL_ACCESS = "full"
READ_ACCESS = "read"
NO_ACCESS = "none"

GROUP_ACCESS = {
    TeamGroups.COLLECTION_ADMIN: {
        "apps": {
            "article": FULL_ACCESS,
            "collection": FULL_ACCESS,
            "core_settings": FULL_ACCESS,
            "django_celery_beat": FULL_ACCESS,
            "doi": FULL_ACCESS,
            "files_storage": FULL_ACCESS,
            "htmlxml": FULL_ACCESS,
            "institution": FULL_ACCESS,
            "issue": FULL_ACCESS,
            "journal": FULL_ACCESS,
            "location": FULL_ACCESS,
            "migration": FULL_ACCESS,
            "package": FULL_ACCESS,
            "pid_provider": FULL_ACCESS,
            "proc": FULL_ACCESS,
            "publication": FULL_ACCESS,
            "researcher": FULL_ACCESS,
            "team": FULL_ACCESS,
            "tracker": FULL_ACCESS,
            "upload": FULL_ACCESS,
        },
        "models": {
            "team": {
                "collectionteammember": CRUD_ACTIONS,
                "company": CRUD_ACTIONS,
            },
            "upload": {"*": CRUD_ACTIONS},
        },
        "custom": {
            "upload": (
                ACCESS_ALL_PACKAGES,
                ASSIGN_PACKAGE,
                FINISH_DEPOSIT,
                PUBLISH_PACKAGE,
                REPUBLISH_PACKAGE,
            ),
            "wagtailadmin": ("access_admin",),
        },
    },
    TeamGroups.COLLECTION_MEMBER: {
        "apps": {
            "article": FULL_ACCESS,
            "collection": FULL_ACCESS,
            "doi": FULL_ACCESS,
            "htmlxml": FULL_ACCESS,
            "institution": FULL_ACCESS,
            "issue": FULL_ACCESS,
            "journal": FULL_ACCESS,
            "location": FULL_ACCESS,
            "migration": FULL_ACCESS,
            "package": FULL_ACCESS,
            "pid_provider": FULL_ACCESS,
            "proc": FULL_ACCESS,
            "publication": FULL_ACCESS,
            "researcher": FULL_ACCESS,
            "team": READ_ACCESS,
            "tracker": FULL_ACCESS,
            "upload": FULL_ACCESS,
        },
        "models": {
            "team": {
                "collectionteammember": VIEW_ACTIONS,
            },
            "upload": {
                "*": VIEW_ACTIONS,
                "package": ("add", "view"),
                "packagezip": ("add", "view"),
                "qapackage": ("change", "view"),
                "readytopublishpackage": ("change", "view"),
                "validationreport": ("change", "view"),
                "xmlerrorreport": ("change", "view"),
                "xmlinforeport": ("change", "view"),
            },
        },
        "custom": {
            "upload": (
                ACCESS_ALL_PACKAGES,
                ASSIGN_PACKAGE,
                FINISH_DEPOSIT,
                PUBLISH_PACKAGE,
                REPUBLISH_PACKAGE,
            ),
            "wagtailadmin": ("access_admin",),
        },
    },
}

STAFF_APPS = {"bigbang", "core"}
