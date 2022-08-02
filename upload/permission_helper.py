from wagtail.contrib.modeladmin.helpers import PermissionHelper


ACCEPT = 'accept'
ENQUEUE_FOR_VALIDATION = 'enqueue_for_validation'
REJECT = 'reject'
PREVIEW = 'preview'
SCHEDULE_FOR_PUBLICATION = 'schedule_for_publication'


class UploadPermissionHelper(PermissionHelper):
    def user_can_accept(self, user, obj):
        return self.user_has_specific_permission(user, ACCEPT)

    def user_can_validate(self, user, obj):
        return self.user_has_specific_permission(user, ENQUEUE_FOR_VALIDATION)

    def user_can_reject(self, user, obj):
        return self.user_has_specific_permission(user, REJECT)

    def user_can_preview(self, user, obj):
        return self.user_has_specific_permission(user, PREVIEW)

    def user_can_publish(self, user, obj):
        return self.user_has_specific_permission(user, SCHEDULE_FOR_PUBLICATION)
