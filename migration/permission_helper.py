from wagtail.contrib.modeladmin.helpers import PermissionHelper

ACCESS_MIGRATION_FAILURES = "access_migration_failures"


class MigrationFailurePermissionHelper(PermissionHelper):
    def user_can_access_all_migration_failures(self, user, obj):
        return self.user_has_specific_permission(user, ACCESS_MIGRATION_FAILURES)
