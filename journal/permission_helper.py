"""Permission helper for journal app."""

from core.permissions import GroupBasedPermissionHelper


class JournalPermissionHelper(GroupBasedPermissionHelper):
    """Permission helper for journal management."""
    app_name = "journal"
