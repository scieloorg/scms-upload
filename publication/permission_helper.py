"""Permission helper for publication app."""

from core.permissions import GroupBasedPermissionHelper


class PublicationPermissionHelper(GroupBasedPermissionHelper):
    """Permission helper for publication management."""
    app_name = "publication"
