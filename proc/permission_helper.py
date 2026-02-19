"""Permission helper for proc app."""

from core.permissions import GroupBasedPermissionHelper


class ProcPermissionHelper(GroupBasedPermissionHelper):
    """Permission helper for process management."""
    app_name = "proc"
