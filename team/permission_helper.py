"""Permission helper for team app."""

from core.permissions import GroupBasedPermissionHelper


class TeamPermissionHelper(GroupBasedPermissionHelper):
    """Permission helper for team management."""
    app_name = "team"
