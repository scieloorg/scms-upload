from wagtail.contrib.modeladmin.helpers import PermissionHelper


REQUEST_CHANGE = 'request_change'


class ArticlePermissionHelper(PermissionHelper):
    def user_can_request_change(self, user, obj):
        return self.user_has_specific_permission(user, REQUEST_CHANGE)
