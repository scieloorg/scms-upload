"""Permission helper for collection app."""

from core.permissions import GroupBasedPermissionHelper


class CollectionPermissionHelper(GroupBasedPermissionHelper):
    """Permission helper for collection management."""
    app_name = "collection"
