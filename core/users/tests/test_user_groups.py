"""Tests for user groups and permissions."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from core.users.user_groups import (
    APP_PERMISSIONS,
    UserGroups,
    get_user_accessible_apps,
    user_can_access_app,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


class TestUserGroups:
    """Test user groups functionality."""

    def test_user_groups_constants(self):
        """Test that all user group constants are defined."""
        assert UserGroups.SUPERADMIN == "Superadmin"
        assert UserGroups.ADMIN_COLLECTION == "Admin Coleção"
        assert UserGroups.ANALYST == "Analista"
        assert UserGroups.XML_PRODUCER == "Produtor XML"
        assert UserGroups.JOURNAL_MANAGER == "Gestor de Periódico"
        assert UserGroups.COMPANY_MANAGER == "Gestor de Empresa"
        assert UserGroups.REVIEWER == "Revisor"

    def test_app_permissions_defined(self):
        """Test that APP_PERMISSIONS contains expected apps."""
        expected_apps = [
            "upload",
            "article",
            "journal",
            "issue",
            "collection",
            "team",
            "institution",
            "location",
            "migration",
            "doi",
            "pid_provider",
            "publication",
            "package",
            "proc",
            "tracker",
        ]
        
        for app in expected_apps:
            assert app in APP_PERMISSIONS, f"App '{app}' not in APP_PERMISSIONS"


class TestUserCanAccessApp:
    """Test user_can_access_app function."""

    def test_superuser_has_access_to_all_apps(self):
        """Test that superusers have access to all apps."""
        user = User.objects.create_user(
            username="superuser",
            email="super@example.com",
            is_superuser=True
        )
        
        # Test access to various apps
        assert user_can_access_app(user, "upload") is True
        assert user_can_access_app(user, "article") is True
        assert user_can_access_app(user, "collection") is True
        assert user_can_access_app(user, "journal") is True

    def test_admin_collection_access(self):
        """Test that Admin Coleção has access to most apps."""
        user = User.objects.create_user(
            username="admin_collection",
            email="admin@example.com"
        )
        group = Group.objects.create(name=UserGroups.ADMIN_COLLECTION)
        user.groups.add(group)
        
        # Should have access to these
        assert user_can_access_app(user, "upload") is True
        assert user_can_access_app(user, "article") is True
        assert user_can_access_app(user, "collection") is True
        assert user_can_access_app(user, "journal") is True

    def test_analyst_access(self):
        """Test that Analyst has appropriate access."""
        user = User.objects.create_user(
            username="analyst",
            email="analyst@example.com"
        )
        group = Group.objects.create(name=UserGroups.ANALYST)
        user.groups.add(group)
        
        # Should have access to these
        assert user_can_access_app(user, "upload") is True
        assert user_can_access_app(user, "article") is True
        assert user_can_access_app(user, "issue") is True
        
        # Should NOT have access to these
        assert user_can_access_app(user, "collection") is False
        assert user_can_access_app(user, "journal") is False

    def test_xml_producer_access(self):
        """Test that XML Producer has limited access."""
        user = User.objects.create_user(
            username="producer",
            email="producer@example.com"
        )
        group = Group.objects.create(name=UserGroups.XML_PRODUCER)
        user.groups.add(group)
        
        # Should have access to these
        assert user_can_access_app(user, "upload") is True
        assert user_can_access_app(user, "package") is True
        
        # Should NOT have access to these
        assert user_can_access_app(user, "article") is False
        assert user_can_access_app(user, "collection") is False
        assert user_can_access_app(user, "journal") is False

    def test_journal_manager_access(self):
        """Test that Journal Manager has appropriate access."""
        user = User.objects.create_user(
            username="journal_manager",
            email="jmanager@example.com"
        )
        group = Group.objects.create(name=UserGroups.JOURNAL_MANAGER)
        user.groups.add(group)
        
        # Should have access to these
        assert user_can_access_app(user, "article") is True
        assert user_can_access_app(user, "journal") is True
        assert user_can_access_app(user, "issue") is True
        assert user_can_access_app(user, "team") is True
        
        # Should NOT have access to these
        assert user_can_access_app(user, "upload") is False
        assert user_can_access_app(user, "collection") is False

    def test_reviewer_access(self):
        """Test that Reviewer has limited read access."""
        user = User.objects.create_user(
            username="reviewer",
            email="reviewer@example.com"
        )
        group = Group.objects.create(name=UserGroups.REVIEWER)
        user.groups.add(group)
        
        # Should have access only to article
        assert user_can_access_app(user, "article") is True
        
        # Should NOT have access to these
        assert user_can_access_app(user, "upload") is False
        assert user_can_access_app(user, "journal") is False
        assert user_can_access_app(user, "collection") is False

    def test_user_with_no_groups(self):
        """Test that user with no groups has no access."""
        user = User.objects.create_user(
            username="nogroup",
            email="nogroup@example.com"
        )
        
        # Should NOT have access to any app
        assert user_can_access_app(user, "upload") is False
        assert user_can_access_app(user, "article") is False
        assert user_can_access_app(user, "collection") is False

    def test_undefined_app_allows_access(self):
        """Test that undefined apps allow access for backward compatibility."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        
        # App not in APP_PERMISSIONS should return True for backward compatibility
        assert user_can_access_app(user, "undefined_app") is True

    def test_user_with_multiple_groups(self):
        """Test that user with multiple groups gets combined access."""
        user = User.objects.create_user(
            username="multigroup",
            email="multi@example.com"
        )
        
        # Add multiple groups
        analyst_group = Group.objects.create(name=UserGroups.ANALYST)
        journal_group = Group.objects.create(name=UserGroups.JOURNAL_MANAGER)
        user.groups.add(analyst_group, journal_group)
        
        # Should have access from both groups
        assert user_can_access_app(user, "upload") is True  # from Analyst
        assert user_can_access_app(user, "journal") is True  # from Journal Manager
        assert user_can_access_app(user, "article") is True  # from both


class TestGetUserAccessibleApps:
    """Test get_user_accessible_apps function."""

    def test_superuser_gets_all_apps(self):
        """Test that superusers get all apps."""
        user = User.objects.create_user(
            username="superuser",
            email="super@example.com",
            is_superuser=True
        )
        
        accessible_apps = get_user_accessible_apps(user)
        
        # Should have access to all defined apps
        assert "upload" in accessible_apps
        assert "article" in accessible_apps
        assert "collection" in accessible_apps
        assert len(accessible_apps) == len(APP_PERMISSIONS)

    def test_analyst_gets_correct_apps(self):
        """Test that analyst gets correct apps."""
        user = User.objects.create_user(
            username="analyst",
            email="analyst@example.com"
        )
        group = Group.objects.create(name=UserGroups.ANALYST)
        user.groups.add(group)
        
        accessible_apps = get_user_accessible_apps(user)
        
        # Should have access to these
        assert "upload" in accessible_apps
        assert "article" in accessible_apps
        assert "issue" in accessible_apps
        
        # Should NOT have access to these
        assert "collection" not in accessible_apps
        assert "journal" not in accessible_apps

    def test_xml_producer_gets_limited_apps(self):
        """Test that XML producer gets limited apps."""
        user = User.objects.create_user(
            username="producer",
            email="producer@example.com"
        )
        group = Group.objects.create(name=UserGroups.XML_PRODUCER)
        user.groups.add(group)
        
        accessible_apps = get_user_accessible_apps(user)
        
        # Should have access to limited apps
        assert "upload" in accessible_apps
        assert "package" in accessible_apps
        
        # Should be a small list
        assert len(accessible_apps) == 2

    def test_user_with_no_groups_gets_empty_list(self):
        """Test that user with no groups gets empty list."""
        user = User.objects.create_user(
            username="nogroup",
            email="nogroup@example.com"
        )
        
        accessible_apps = get_user_accessible_apps(user)
        
        # Should have no apps
        assert len(accessible_apps) == 0

    def test_user_with_multiple_groups_gets_combined_apps(self):
        """Test that user with multiple groups gets combined apps."""
        user = User.objects.create_user(
            username="multigroup",
            email="multi@example.com"
        )
        
        # Add multiple groups
        analyst_group = Group.objects.create(name=UserGroups.ANALYST)
        reviewer_group = Group.objects.create(name=UserGroups.REVIEWER)
        user.groups.add(analyst_group, reviewer_group)
        
        accessible_apps = get_user_accessible_apps(user)
        
        # Should have apps from both groups
        assert "upload" in accessible_apps  # from Analyst
        assert "article" in accessible_apps  # from both
        
        # No duplicates
        assert len(accessible_apps) == len(set(accessible_apps))
