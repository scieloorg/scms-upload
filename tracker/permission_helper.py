"""Permission helper for tracker app."""

from core.permissions import GroupBasedPermissionHelper


class TrackerPermissionHelper(GroupBasedPermissionHelper):
    """Permission helper for tracker management."""
    app_name = "tracker"
