"""
User groups and permissions configuration for SCMS Upload.

This module defines the user groups and their permissions for accessing
different administrative areas of the system.
"""

from django.utils.translation import gettext_lazy as _


# User group names
class UserGroups:
    """User group names for the system."""
    
    SUPERADMIN = "Superadmin"
    ADMIN_COLLECTION = "Admin Coleção"
    ANALYST = "Analista"
    XML_PRODUCER = "Produtor XML"
    JOURNAL_MANAGER = "Gestor de Periódico"
    COMPANY_MANAGER = "Gestor de Empresa"
    REVIEWER = "Revisor"


# Permission matrix: App -> Groups that can access
# This defines which user groups have access to which apps in the admin area
APP_PERMISSIONS = {
    # Upload module - for package management and XML upload
    "upload": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
        UserGroups.XML_PRODUCER,
    ],
    
    # Article management
    "article": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
        UserGroups.JOURNAL_MANAGER,
        UserGroups.REVIEWER,
    ],
    
    # Journal management
    "journal": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.JOURNAL_MANAGER,
    ],
    
    # Issue management
    "issue": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
        UserGroups.JOURNAL_MANAGER,
    ],
    
    # Collection management - administrative access only
    "collection": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
    ],
    
    # Team management
    "team": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.JOURNAL_MANAGER,
        UserGroups.COMPANY_MANAGER,
    ],
    
    # Institution management
    "institution": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
    ],
    
    # Location management
    "location": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
    ],
    
    # Migration management
    "migration": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
    ],
    
    # DOI management
    "doi": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
    ],
    
    # PID Provider management
    "pid_provider": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
    ],
    
    # Publication management
    "publication": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
    ],
    
    # Package tracking
    "package": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
        UserGroups.XML_PRODUCER,
    ],
    
    # Process management
    "proc": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
    ],
    
    # Tracker
    "tracker": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
    ],
    
    # File storage
    "files_storage": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
    ],
    
    # HTML/XML management
    "htmlxml": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
    ],
    
    # Researcher management
    "researcher": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
        UserGroups.ANALYST,
    ],
    
    # Core settings
    "core_settings": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
    ],
    
    # Django Celery Beat (task scheduling)
    "django_celery_beat": [
        UserGroups.SUPERADMIN,
        UserGroups.ADMIN_COLLECTION,
    ],
}


def user_can_access_app(user, app_name):
    """
    Check if a user can access a specific app based on their groups.
    
    Args:
        user: Django User object
        app_name: Name of the app (e.g., 'upload', 'article')
    
    Returns:
        bool: True if user can access the app
    """
    # Superusers always have access
    if user.is_superuser:
        return True
    
    # Check if app has permissions defined
    if app_name not in APP_PERMISSIONS:
        # If no specific permissions, allow access (backward compatibility)
        return True
    
    # Get allowed groups for this app
    allowed_groups = APP_PERMISSIONS.get(app_name, [])
    
    # Check if user is in any of the allowed groups
    user_groups = user.groups.values_list('name', flat=True)
    return any(group in allowed_groups for group in user_groups)


def get_user_accessible_apps(user):
    """
    Get list of apps that a user can access based on their groups.
    
    Args:
        user: Django User object
    
    Returns:
        list: List of app names the user can access
    """
    if user.is_superuser:
        return list(APP_PERMISSIONS.keys())
    
    user_groups = set(user.groups.values_list('name', flat=True))
    accessible_apps = []
    
    for app_name, allowed_groups in APP_PERMISSIONS.items():
        if any(group in allowed_groups for group in user_groups):
            accessible_apps.append(app_name)
    
    return accessible_apps


# Group descriptions for migration
GROUP_DESCRIPTIONS = {
    UserGroups.SUPERADMIN: _("Full system access with all permissions"),
    UserGroups.ADMIN_COLLECTION: _("Collection administrator with broad access to manage collections"),
    UserGroups.ANALYST: _("Quality analyst who reviews and validates packages"),
    UserGroups.XML_PRODUCER: _("XML producer who uploads and manages packages"),
    UserGroups.JOURNAL_MANAGER: _("Journal manager who manages journal content"),
    UserGroups.COMPANY_MANAGER: _("Company manager who manages company team and contracts"),
    UserGroups.REVIEWER: _("Content reviewer with read access to articles"),
}
