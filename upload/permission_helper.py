from wagtail.contrib.modeladmin.helpers import PermissionHelper


ACCESS_ALL_PACKAGES = 'access_all_packages'
FINISH_DEPOSIT = 'finish_deposit'


class UploadPermissionHelper(PermissionHelper):
    def user_can_access_all_packages(self, user, obj):
        return self.user_has_specific_permission(user, ACCESS_ALL_PACKAGES)

    def user_can_finish_deposit(self, user, obj):
        return self.user_has_specific_permission(user, FINISH_DEPOSIT)

