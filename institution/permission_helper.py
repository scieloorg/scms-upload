"""Permission helper for institution app."""

from core.permissions import GroupBasedPermissionHelper


class InstitutionPermissionHelper(GroupBasedPermissionHelper):
    """Permission helper for institution management."""
    app_name = "institution"
