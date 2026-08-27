from team.constants import TeamGroups
from upload.permissions import (
    ACCESS_PACKAGES,
    ASSIGN_PACKAGE,
    FINISH_DEPOSIT,
    PUBLISH_PACKAGE,
    REPUBLISH_PACKAGE,
)

MANAGE_ACTIONS = ("add", "change", "view")
VIEW_ACTIONS = ("view",)
FULL_ACCESS = "full"
READ_ACCESS = "read"
NO_ACCESS = "none"


def build_group_access(app_access):
    group_access = {
        group_name: {"apps": {}, "models": {}, "custom": {}}
        for group_name in TeamGroups.ALL
    }

    for app_name, groups in app_access.items():
        for group_name, rules in groups.items():
            if "access" in rules:
                group_access[group_name]["apps"][app_name] = rules["access"]
            if "models" in rules:
                group_access[group_name]["models"][app_name] = rules["models"]
            if "custom" in rules:
                group_access[group_name]["custom"][app_name] = rules["custom"]

    return group_access


APP_ACCESS = {
    "article": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
        TeamGroups.JOURNAL_ADMIN: {"access": READ_ACCESS},
        TeamGroups.JOURNAL_MEMBER: {"access": READ_ACCESS},
    },
    "collection": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
    },
    "core_settings": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
    },
    "django_celery_beat": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
    },
    "doi": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
    },
    "files_storage": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
    },
    "htmlxml": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
    },
    "institution": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
        TeamGroups.JOURNAL_ADMIN: {"access": READ_ACCESS},
        TeamGroups.JOURNAL_MEMBER: {"access": READ_ACCESS},
        TeamGroups.COMPANY_ADMIN: {"access": READ_ACCESS},
        TeamGroups.COMPANY_MEMBER: {"access": READ_ACCESS},
    },
    "issue": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
        TeamGroups.JOURNAL_ADMIN: {"access": READ_ACCESS},
        TeamGroups.JOURNAL_MEMBER: {"access": READ_ACCESS},
        TeamGroups.COMPANY_ADMIN: {"access": READ_ACCESS},
        TeamGroups.COMPANY_MEMBER: {"access": READ_ACCESS},
    },
    "journal": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
        TeamGroups.JOURNAL_ADMIN: {"access": READ_ACCESS},
        TeamGroups.JOURNAL_MEMBER: {"access": READ_ACCESS},
        TeamGroups.COMPANY_ADMIN: {"access": READ_ACCESS},
        TeamGroups.COMPANY_MEMBER: {"access": READ_ACCESS},
    },
    "location": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
        TeamGroups.JOURNAL_ADMIN: {"access": READ_ACCESS},
        TeamGroups.JOURNAL_MEMBER: {"access": READ_ACCESS},
        TeamGroups.COMPANY_ADMIN: {"access": READ_ACCESS},
        TeamGroups.COMPANY_MEMBER: {"access": READ_ACCESS},
    },
    "migration": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
    },
    "package": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
    },
    "pid_provider": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
    },
    "proc": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
    },
    "publication": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
    },
    "researcher": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
    },
    "team": {
        TeamGroups.COLLECTION_ADMIN: {
            "access": FULL_ACCESS,
            "models": {
                "collectionteammember": MANAGE_ACTIONS,
                "company": MANAGE_ACTIONS,
            },
        },
        TeamGroups.COLLECTION_MEMBER: {
            "access": READ_ACCESS,
            "models": {
                "collectionteammember": VIEW_ACTIONS,
            },
        },
        TeamGroups.JOURNAL_ADMIN: {
            "access": FULL_ACCESS,
            "models": {
                "journalcompanycontract": MANAGE_ACTIONS,
                "journalteammember": MANAGE_ACTIONS,
            },
        },
        TeamGroups.JOURNAL_MEMBER: {
            "access": READ_ACCESS,
            "models": {
                "journalcompanycontract": VIEW_ACTIONS,
                "journalteammember": VIEW_ACTIONS,
            },
        },
        TeamGroups.COMPANY_ADMIN: {
            "access": FULL_ACCESS,
            "models": {
                "company": VIEW_ACTIONS,
                "companyteammember": MANAGE_ACTIONS,
                "journalcompanycontract": VIEW_ACTIONS,
            },
        },
        TeamGroups.COMPANY_MEMBER: {
            "access": READ_ACCESS,
            "models": {
                "company": VIEW_ACTIONS,
                "companyteammember": VIEW_ACTIONS,
                "journalcompanycontract": VIEW_ACTIONS,
            },
        },
    },
    "tracker": {
        TeamGroups.COLLECTION_ADMIN: {"access": FULL_ACCESS},
        TeamGroups.COLLECTION_MEMBER: {"access": FULL_ACCESS},
    },
    "upload": {
        TeamGroups.COLLECTION_ADMIN: {
            "access": FULL_ACCESS,
            "models": {"*": MANAGE_ACTIONS},
            "custom": (
                ACCESS_PACKAGES,
                ASSIGN_PACKAGE,
                FINISH_DEPOSIT,
                PUBLISH_PACKAGE,
                REPUBLISH_PACKAGE,
            ),
        },
        TeamGroups.COLLECTION_MEMBER: {
            "access": FULL_ACCESS,
            "models": {
                "*": VIEW_ACTIONS,
                "package": ("add", "view"),
                "packagezip": ("add", "view"),
                "qapackage": ("change", "view"),
                "readytopublishpackage": ("change", "view"),
                "validationreport": ("change", "view"),
                "xmlerrorreport": ("change", "view"),
                "xmlinforeport": ("change", "view"),
            },
            "custom": (
                ACCESS_PACKAGES,
                ASSIGN_PACKAGE,
                FINISH_DEPOSIT,
                PUBLISH_PACKAGE,
                REPUBLISH_PACKAGE,
            ),
        },
        TeamGroups.JOURNAL_ADMIN: {
            "access": FULL_ACCESS,
            "models": {
                "*": VIEW_ACTIONS,
                "package": ("add", "view"),
                "packagezip": ("add", "view"),
                "validationreport": ("change", "view"),
                "xmlerrorreport": ("change", "view"),
                "xmlinforeport": ("change", "view"),
            },
            "custom": (ACCESS_PACKAGES, FINISH_DEPOSIT),
        },
        TeamGroups.JOURNAL_MEMBER: {
            "access": FULL_ACCESS,
            "models": {
                "*": VIEW_ACTIONS,
                "package": ("add", "view"),
                "packagezip": ("add", "view"),
                "validationreport": ("change", "view"),
                "xmlerrorreport": ("change", "view"),
                "xmlinforeport": ("change", "view"),
            },
            "custom": (ACCESS_PACKAGES, FINISH_DEPOSIT),
        },
        TeamGroups.COMPANY_ADMIN: {
            "access": FULL_ACCESS,
            "models": {
                "*": VIEW_ACTIONS,
                "package": ("add", "view"),
                "packagezip": ("add", "view"),
                "validationreport": ("change", "view"),
                "xmlerrorreport": ("change", "view"),
                "xmlinforeport": ("change", "view"),
            },
            "custom": (FINISH_DEPOSIT,),
        },
        TeamGroups.COMPANY_MEMBER: {
            "access": FULL_ACCESS,
            "models": {
                "*": VIEW_ACTIONS,
                "package": ("add", "view"),
                "packagezip": ("add", "view"),
                "validationreport": ("change", "view"),
                "xmlerrorreport": ("change", "view"),
                "xmlinforeport": ("change", "view"),
            },
            "custom": (FINISH_DEPOSIT,),
        },
    },
    "wagtailadmin": {
        TeamGroups.COLLECTION_ADMIN: {"custom": ("access_admin",)},
        TeamGroups.COLLECTION_MEMBER: {"custom": ("access_admin",)},
        TeamGroups.JOURNAL_ADMIN: {"custom": ("access_admin",)},
        TeamGroups.JOURNAL_MEMBER: {"custom": ("access_admin",)},
        TeamGroups.COMPANY_ADMIN: {"custom": ("access_admin",)},
        TeamGroups.COMPANY_MEMBER: {"custom": ("access_admin",)},
    },
}

GROUP_ACCESS = build_group_access(APP_ACCESS)

STAFF_APPS = {"bigbang", "core"}
