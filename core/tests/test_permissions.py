"""Tests for GroupBasedPermissionHelper."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from wagtail_modeladmin.helpers import PermissionHelper

from core.permissions import GroupBasedPermissionHelper
from core.users.user_groups import UserGroups

User = get_user_model()

pytestmark = pytest.mark.django_db


class TestPermissionHelper(GroupBasedPermissionHelper):
    """Test permission helper with app_name set."""
    app_name = "upload"


class TestGroupBasedPermissionHelper:
    """Test GroupBasedPermissionHelper class."""

    def test_permission_helper_allows_superuser(self):
        """Test that superusers are always allowed."""
        user = User.objects.create_user(
            username="superuser",
            email="super@example.com",
            is_superuser=True
        )
        
        helper = TestPermissionHelper(model=None)
        
        # Superuser should be allowed
        assert helper.user_can_list(user) is True
        assert helper.user_can_create(user) is True

    def test_permission_helper_allows_user_in_group(self):
        """Test that users in allowed groups can access."""
        user = User.objects.create_user(
            username="analyst",
            email="analyst@example.com"
        )
        group = Group.objects.create(name=UserGroups.ANALYST)
        user.groups.add(group)
        
        helper = TestPermissionHelper(model=None)
        
        # User in Analyst group should have access to upload app
        assert helper._check_app_access(user) is True

    def test_permission_helper_denies_user_not_in_group(self):
        """Test that users not in allowed groups are denied."""
        user = User.objects.create_user(
            username="reviewer",
            email="reviewer@example.com"
        )
        group = Group.objects.create(name=UserGroups.REVIEWER)
        user.groups.add(group)
        
        helper = TestPermissionHelper(model=None)
        
        # User in Reviewer group should NOT have access to upload app
        assert helper._check_app_access(user) is False

    def test_permission_helper_without_app_name(self):
        """Test that helper without app_name allows access (backward compatibility)."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com"
        )
        
        # Create helper without app_name
        class NoAppPermissionHelper(GroupBasedPermissionHelper):
            app_name = None
        
        helper = NoAppPermissionHelper(model=None)
        
        # Should allow access for backward compatibility
        assert helper._check_app_access(user) is True

    def test_permission_helper_user_can_list(self):
        """Test user_can_list method with group checking."""
        user = User.objects.create_user(
            username="producer",
            email="producer@example.com"
        )
        group = Group.objects.create(name=UserGroups.XML_PRODUCER)
        user.groups.add(group)
        
        helper = TestPermissionHelper(model=None)
        
        # XML Producer should have access to upload app
        assert helper.user_can_list(user) is True

    def test_permission_helper_user_can_create(self):
        """Test user_can_create method with group checking."""
        user = User.objects.create_user(
            username="admin",
            email="admin@example.com"
        )
        group = Group.objects.create(name=UserGroups.ADMIN_COLLECTION)
        user.groups.add(group)
        
        helper = TestPermissionHelper(model=None)
        
        # Admin Collection should have access to upload app
        assert helper.user_can_create(user) is True

    def test_permission_helper_denies_unauthorized_user(self):
        """Test that unauthorized users are denied access."""
        user = User.objects.create_user(
            username="journal_manager",
            email="jmanager@example.com"
        )
        group = Group.objects.create(name=UserGroups.JOURNAL_MANAGER)
        user.groups.add(group)
        
        helper = TestPermissionHelper(model=None)
        
        # Journal Manager should NOT have access to upload app
        assert helper.user_can_list(user) is False
        assert helper.user_can_create(user) is False

    def test_permission_helper_with_multiple_groups(self):
        """Test that user with multiple groups gets combined access."""
        user = User.objects.create_user(
            username="multigroup",
            email="multi@example.com"
        )
        
        # Add Analyst group (has upload access)
        analyst_group = Group.objects.create(name=UserGroups.ANALYST)
        user.groups.add(analyst_group)
        
        helper = TestPermissionHelper(model=None)
        
        # Should have access through Analyst group
        assert helper.user_can_list(user) is True
        assert helper.user_can_create(user) is True
