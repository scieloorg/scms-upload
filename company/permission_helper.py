from wagtail_modeladmin.helpers import PermissionHelper

from company.models import CompanyMember


class CompanyPermissionHelper(PermissionHelper):
    """
    Permission helper for Company model.
    Managers have full permissions. Members have limited permissions.
    """

    def user_can_create(self, user):
        """Any authenticated user can create a company."""
        return user.is_authenticated

    def user_can_edit_obj(self, user, obj):
        """
        User can edit a company if they are a manager of that company,
        or if they are a superuser.
        """
        if user.is_superuser:
            return True
        return obj.has_manager(user)

    def user_can_delete_obj(self, user, obj):
        """
        User can delete a company if they are a manager of that company,
        or if they are a superuser.
        """
        if user.is_superuser:
            return True
        return obj.has_manager(user)

    def user_can_inspect_obj(self, user, obj):
        """
        User can inspect a company if they are a member (any role) of that company,
        or if they are a superuser.
        """
        if user.is_superuser:
            return True
        return obj.has_member(user)


class CompanyMemberPermissionHelper(PermissionHelper):
    """
    Permission helper for CompanyMember model.
    Only company managers can manage team members.
    """

    def user_can_create(self, user):
        """
        User can add a member if they are a manager of at least one company.
        """
        if user.is_superuser:
            return True
        return CompanyMember.objects.filter(
            user=user,
            role=CompanyMember.MANAGER,
            is_active_member=True,
        ).exists()

    def user_can_edit_obj(self, user, obj):
        """
        User can edit a member if they are a manager of the same company.
        """
        if user.is_superuser:
            return True
        return CompanyMember.objects.filter(
            company=obj.company,
            user=user,
            role=CompanyMember.MANAGER,
            is_active_member=True,
        ).exists()

    def user_can_delete_obj(self, user, obj):
        """
        User can delete a member if they are a manager of the same company.
        """
        if user.is_superuser:
            return True
        return CompanyMember.objects.filter(
            company=obj.company,
            user=user,
            role=CompanyMember.MANAGER,
            is_active_member=True,
        ).exists()

    def user_can_inspect_obj(self, user, obj):
        """
        User can inspect a member if they are a member of the same company.
        """
        if user.is_superuser:
            return True
        return CompanyMember.objects.filter(
            company=obj.company,
            user=user,
            is_active_member=True,
        ).exists()
