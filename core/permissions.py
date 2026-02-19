"""
Base permission helper for group-based access control.
"""

from wagtail_modeladmin.helpers import PermissionHelper

from core.users.user_groups import user_can_access_app


class GroupBasedPermissionHelper(PermissionHelper):
    """
    Permission helper that checks user groups for access control.
    
    This extends Wagtail's PermissionHelper to add group-based access control
    on top of the existing permission system.
    """
    
    # Override this in subclasses to specify which app this helper is for
    app_name = None
    
    def user_can_list(self, user):
        """Check if user can list objects in this app."""
        if not self._check_app_access(user):
            return False
        return super().user_can_list(user)
    
    def user_can_create(self, user):
        """Check if user can create objects in this app."""
        if not self._check_app_access(user):
            return False
        return super().user_can_create(user)
    
    def user_can_inspect_obj(self, user, obj):
        """Check if user can inspect a specific object."""
        if not self._check_app_access(user):
            return False
        return super().user_can_inspect_obj(user, obj)
    
    def user_can_edit_obj(self, user, obj):
        """Check if user can edit a specific object."""
        if not self._check_app_access(user):
            return False
        return super().user_can_edit_obj(user, obj)
    
    def user_can_delete_obj(self, user, obj):
        """Check if user can delete a specific object."""
        if not self._check_app_access(user):
            return False
        return super().user_can_delete_obj(user, obj)
    
    def _check_app_access(self, user):
        """
        Check if user's groups allow access to this app.
        
        Returns:
            bool: True if user can access this app
        """
        if not self.app_name:
            # If no app_name specified, allow access (backward compatibility)
            return True
        
        return user_can_access_app(user, self.app_name)
