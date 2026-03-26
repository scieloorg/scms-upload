"""
Permissões específicas do módulo Upload.

Herda de core.permissions.AppPermissions e define as regras de negócio
próprias: quem pode acessar, quem é analista, permissões granulares.
"""

from core.permission_helper import AppPermissions
from team.models import has_permission, CollectionTeamMember


# Codenames de permissões específicas do Upload
ACCESS_ALL_PACKAGES = "access_all_packages"
ASSIGN_PACKAGE = "assign_package"
FINISH_DEPOSIT = "finish_deposit"
SEND_VALIDATION_ERROR_RESOLUTION = "send_validation_error_resolution"
ANALYSE_VALIDATION_ERROR_RESOLUTION = "analyse_validation_error_resolution"


class UploadPermissions(AppPermissions):
    app_label = "upload"

    @staticmethod
    def user_can_access(user):
        """Verifica se o usuário tem acesso ao módulo Upload."""
        return has_permission(user)

    @staticmethod
    def user_is_staff(user):
        """Verifica se o usuário é membro de equipe analista."""
        if UploadPermissions.user_can_access(user):
            return CollectionTeamMember.objects.filter(user=user).exists()
        return False

    @classmethod
    def user_can_access_all_packages(cls, user):
        return cls.user_has_permission(user, ACCESS_ALL_PACKAGES)

    @classmethod
    def user_can_assign_package(cls, user):
        return cls.user_has_permission(user, ASSIGN_PACKAGE)

    @classmethod
    def user_can_finish_deposit(cls, user):
        return cls.user_has_permission(user, FINISH_DEPOSIT)

    @classmethod
    def user_can_send_error_validation_resolution(cls, user):
        return cls.user_has_permission(user, SEND_VALIDATION_ERROR_RESOLUTION)

    @classmethod
    def user_can_analyse_error_validation_resolution(cls, user):
        return cls.user_has_permission(user, ANALYSE_VALIDATION_ERROR_RESOLUTION)
