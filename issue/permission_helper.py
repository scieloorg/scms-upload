"""Permission helper for issue app."""

from core.permissions import GroupBasedPermissionHelper


class IssuePermissionHelper(GroupBasedPermissionHelper):
    """Permission helper for issue management."""
    app_name = "issue"
