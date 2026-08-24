from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.test import TestCase

from collection.models import Collection
from team.constants import TeamGroups
from team.models import CollectionTeamMember, TeamRole
from team.signals import system_group_update

User = get_user_model()


class GroupSyncSignalTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="member")
        self.collection = Collection.objects.create(
            acron="TST",
            name="Test Collection",
            creator=self.user,
        )

    def test_active_role_defines_canonical_group(self):
        member = CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            role=TeamRole.MEMBER,
            creator=self.user,
        )

        assert self.user.groups.filter(name=TeamGroups.COLLECTION_MEMBER).exists()

        member.role = TeamRole.MANAGER
        member.save()

        assert self.user.groups.filter(name=TeamGroups.COLLECTION_ADMIN).exists()
        assert not self.user.groups.filter(name=TeamGroups.COLLECTION_MEMBER).exists()

    def test_inactive_or_deleted_membership_removes_group(self):
        member = CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            role=TeamRole.MANAGER,
            creator=self.user,
        )

        member.is_active_member = False
        member.save()
        assert not self.user.groups.filter(name=TeamGroups.COLLECTION_ADMIN).exists()

        member.is_active_member = True
        member.save()
        member.delete()
        assert not self.user.groups.filter(name=TeamGroups.COLLECTION_ADMIN).exists()

    def test_replacing_user_reconciles_both_users(self):
        replacement = User.objects.create_user(username="replacement")
        member = CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            role=TeamRole.MANAGER,
            creator=self.user,
        )

        member.user = replacement
        member.save()

        assert not self.user.groups.filter(name=TeamGroups.COLLECTION_ADMIN).exists()
        assert replacement.groups.filter(name=TeamGroups.COLLECTION_ADMIN).exists()

    def test_deleting_collection_reconciles_affected_users(self):
        member = CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            role=TeamRole.MANAGER,
            creator=self.user,
        )

        self.collection.delete()
        member.refresh_from_db()

        assert member.collection is None
        assert not self.user.groups.filter(name=TeamGroups.COLLECTION_ADMIN).exists()


class CanonicalGroupProtectionTest(TestCase):
    def setUp(self):
        with system_group_update():
            self.group, _ = Group.objects.get_or_create(
                name=TeamGroups.COLLECTION_ADMIN
            )

    def test_rejects_manual_membership_and_permission_changes(self):
        user = User.objects.create_user(username="protected")
        permission = Permission.objects.exclude(group=self.group).first()

        with self.assertRaises(PermissionDenied), transaction.atomic():
            user.groups.add(self.group)

        with self.assertRaises(PermissionDenied), transaction.atomic():
            self.group.permissions.add(permission)

    def test_rejects_rename_and_delete(self):
        self.group.name = "RENAMED"
        with self.assertRaises(PermissionDenied), transaction.atomic():
            self.group.save()

        self.group.refresh_from_db()
        with self.assertRaises(PermissionDenied), transaction.atomic():
            self.group.delete()
