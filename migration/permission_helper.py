from wagtail_modeladmin.helpers import PermissionHelper

from core.permissions import GroupBasedPermissionHelper

ACCESS_MIGRATION_FAILURES = "access_migration_failures"


class MigrationFailurePermissionHelper(GroupBasedPermissionHelper):
    app_name = "migration"
    
    def user_can_access_all_migration_failures(self, user, obj):
        return self.user_has_specific_permission(user, ACCESS_MIGRATION_FAILURES)
