from wagtail_modeladmin.helpers import PermissionHelper

from team.models import has_permission, CollectionTeamMember


ACCESS_ALL_PACKAGES = "access_all_packages"
ASSIGN_PACKAGE = "assign_package"
FINISH_DEPOSIT = "finish_deposit"
SEND_VALIDATION_ERROR_RESOLUTION = "send_validation_error_resolution"
ANALYSE_VALIDATION_ERROR_RESOLUTION = "analyse_validation_error_resolution"


class UploadPermissionHelper(PermissionHelper):
    def user_can_packagezip_create(self, user, obj):
        return self.user_can_use_upload_module(user, obj)

    def user_can_use_upload_module(self, user, obj):
        return has_permission(user)
        
    def user_can_access_all_packages(self, user, obj):
        return self.user_has_specific_permission(user, ACCESS_ALL_PACKAGES)

    def user_can_assign_package(self, user, obj):
        return self.user_has_specific_permission(user, ASSIGN_PACKAGE)

    def user_can_finish_deposit(self, user, obj):
        return self.user_has_specific_permission(user, FINISH_DEPOSIT)

    def user_can_send_error_validation_resolution(self, user, obj):
        return self.user_has_specific_permission(user, SEND_VALIDATION_ERROR_RESOLUTION)

    def user_can_analyse_error_validation_resolution(self, user, obj):
        return self.user_has_specific_permission(
            user, ANALYSE_VALIDATION_ERROR_RESOLUTION
        )

    def user_is_analyst_team_member(self, user, obj):
        if self.user_can_use_upload_module(user, obj):
            return CollectionTeamMember.objects.filter(user=user).exists()

    def user_is_xml_producer(self, user, obj):
        if self.user_can_use_upload_module(user, obj):
            return not self.user_is_analyst_team_member(user, obj)
