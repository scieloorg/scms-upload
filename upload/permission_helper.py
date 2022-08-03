from wagtail.contrib.modeladmin.helpers import PermissionHelper


FINISH_DEPOSIT = 'finish_deposit'


class UploadPermissionHelper(PermissionHelper):
    def user_can_finish_deposit(self, user, obj):
        return self.user_has_specific_permission(user, FINISH_DEPOSIT)
