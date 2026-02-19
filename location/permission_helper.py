"""Permission helper for location app."""

from core.permissions import GroupBasedPermissionHelper


class LocationPermissionHelper(GroupBasedPermissionHelper):
    """Permission helper for location management."""
    app_name = "location"
