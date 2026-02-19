from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection, WebSiteConfiguration
from files_storage.models import MinioConfiguration
from migration.models import ClassicWebsiteConfiguration
from team.models import CollectionTeamMember, TeamRole

User = get_user_model()


def _get_user_collection_ids(user):
    return CollectionTeamMember.objects.filter(
        user=user, is_active_member=True
    ).values_list("collection_id", flat=True)


def _is_collection_team_member(user):
    return CollectionTeamMember.objects.filter(
        user=user, is_active_member=True
    ).exists()


class CollectionTeamHelperFunctionsTest(TestCase):
    """Tests for the collection access-control helper functions."""

    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="pass"
        )
        self.active_member = User.objects.create_user(
            username="active", email="active@example.com", password="pass"
        )
        self.inactive_member = User.objects.create_user(
            username="inactive", email="inactive@example.com", password="pass"
        )
        self.non_member = User.objects.create_user(
            username="nonmember", email="nonmember@example.com", password="pass"
        )
        self.col = Collection.objects.create(acron="X", name="Collection X", creator=self.creator)
        CollectionTeamMember.objects.create(
            user=self.active_member,
            collection=self.col,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.creator,
        )
        CollectionTeamMember.objects.create(
            user=self.inactive_member,
            collection=self.col,
            role=TeamRole.MEMBER,
            is_active_member=False,
            creator=self.creator,
        )

    def test_get_user_collection_ids_returns_active_memberships(self):
        ids = _get_user_collection_ids(self.active_member)
        self.assertIn(self.col.id, ids)

    def test_get_user_collection_ids_excludes_inactive_memberships(self):
        ids = _get_user_collection_ids(self.inactive_member)
        self.assertNotIn(self.col.id, ids)

    def test_get_user_collection_ids_empty_for_non_member(self):
        ids = _get_user_collection_ids(self.non_member)
        self.assertFalse(ids.exists())

    def test_is_collection_team_member_true_for_active(self):
        self.assertTrue(_is_collection_team_member(self.active_member))

    def test_is_collection_team_member_false_for_inactive(self):
        self.assertFalse(_is_collection_team_member(self.inactive_member))

    def test_is_collection_team_member_false_for_non_member(self):
        self.assertFalse(_is_collection_team_member(self.non_member))


class CollectionViewSetQueryFilterTest(TestCase):
    """Tests for get_queryset filtering logic on Collection model."""

    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="pass"
        )
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass"
        )
        self.collection_member = User.objects.create_user(
            username="col_member", email="col@example.com", password="pass"
        )
        self.other_user = User.objects.create_user(
            username="other", email="other@example.com", password="pass"
        )
        self.col_a = Collection.objects.create(acron="A", name="Collection A", creator=self.creator)
        self.col_b = Collection.objects.create(acron="B", name="Collection B", creator=self.creator)
        CollectionTeamMember.objects.create(
            user=self.collection_member,
            collection=self.col_a,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.creator,
        )

    def _filtered_qs(self, user):
        """Simulate the CollectionViewSet.get_queryset filtering logic."""
        qs = Collection.objects.all()
        if user.is_superuser:
            return qs
        collection_ids = _get_user_collection_ids(user)
        if collection_ids.exists():
            return qs.filter(id__in=collection_ids)
        return qs.none()

    def test_superuser_sees_all_collections(self):
        qs = self._filtered_qs(self.superuser)
        self.assertIn(self.col_a, qs)
        self.assertIn(self.col_b, qs)

    def test_collection_team_member_sees_only_own_collection(self):
        qs = self._filtered_qs(self.collection_member)
        self.assertIn(self.col_a, qs)
        self.assertNotIn(self.col_b, qs)

    def test_non_collection_team_user_sees_nothing(self):
        qs = self._filtered_qs(self.other_user)
        self.assertEqual(qs.count(), 0)


class WebSiteConfigurationQueryFilterTest(TestCase):
    """Tests for get_queryset filtering logic on WebSiteConfiguration model."""

    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="pass"
        )
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass"
        )
        self.collection_member = User.objects.create_user(
            username="col_member", email="col@example.com", password="pass"
        )
        self.other_user = User.objects.create_user(
            username="other", email="other@example.com", password="pass"
        )
        self.col_a = Collection.objects.create(acron="A", name="Collection A", creator=self.creator)
        self.col_b = Collection.objects.create(acron="B", name="Collection B", creator=self.creator)
        CollectionTeamMember.objects.create(
            user=self.collection_member,
            collection=self.col_a,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.creator,
        )
        self.ws_a = WebSiteConfiguration.objects.create(
            collection=self.col_a, url="http://a.example.com", enabled=True, creator=self.creator
        )
        self.ws_b = WebSiteConfiguration.objects.create(
            collection=self.col_b, url="http://b.example.com", enabled=True, creator=self.creator
        )

    def _filtered_qs(self, user):
        qs = WebSiteConfiguration.objects.all()
        if user.is_superuser:
            return qs
        collection_ids = _get_user_collection_ids(user)
        if collection_ids.exists():
            return qs.filter(collection_id__in=collection_ids)
        return qs.none()

    def test_superuser_sees_all_website_configs(self):
        qs = self._filtered_qs(self.superuser)
        self.assertIn(self.ws_a, qs)
        self.assertIn(self.ws_b, qs)

    def test_collection_team_member_sees_only_own_collection_config(self):
        qs = self._filtered_qs(self.collection_member)
        self.assertIn(self.ws_a, qs)
        self.assertNotIn(self.ws_b, qs)

    def test_non_collection_team_user_sees_nothing(self):
        qs = self._filtered_qs(self.other_user)
        self.assertEqual(qs.count(), 0)


class MinioConfigurationQueryFilterTest(TestCase):
    """Tests for get_queryset filtering logic on MinioConfiguration model."""

    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="pass"
        )
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass"
        )
        self.collection_member = User.objects.create_user(
            username="col_member", email="col@example.com", password="pass"
        )
        self.other_user = User.objects.create_user(
            username="other", email="other@example.com", password="pass"
        )
        self.col = Collection.objects.create(acron="A", name="Collection A", creator=self.creator)
        CollectionTeamMember.objects.create(
            user=self.collection_member,
            collection=self.col,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.creator,
        )
        self.minio = MinioConfiguration.objects.create(
            name="minio1", host="minio.example.com", bucket_root="root", creator=self.creator
        )

    def _filtered_qs(self, user):
        qs = MinioConfiguration.objects.all()
        if user.is_superuser:
            return qs
        if _is_collection_team_member(user):
            return qs
        return qs.none()

    def test_superuser_sees_all_minio_configs(self):
        qs = self._filtered_qs(self.superuser)
        self.assertIn(self.minio, qs)

    def test_collection_team_member_sees_all_minio_configs(self):
        qs = self._filtered_qs(self.collection_member)
        self.assertIn(self.minio, qs)

    def test_non_collection_team_user_sees_nothing(self):
        qs = self._filtered_qs(self.other_user)
        self.assertEqual(qs.count(), 0)


class ClassicWebsiteConfigurationQueryFilterTest(TestCase):
    """Tests for get_queryset filtering logic on ClassicWebsiteConfiguration model."""

    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="pass"
        )
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass"
        )
        self.collection_member = User.objects.create_user(
            username="col_member", email="col@example.com", password="pass"
        )
        self.other_user = User.objects.create_user(
            username="other", email="other@example.com", password="pass"
        )
        self.col_a = Collection.objects.create(acron="A", name="Collection A", creator=self.creator)
        self.col_b = Collection.objects.create(acron="B", name="Collection B", creator=self.creator)
        CollectionTeamMember.objects.create(
            user=self.collection_member,
            collection=self.col_a,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.creator,
        )
        self.cwc_a = ClassicWebsiteConfiguration.objects.create(
            collection=self.col_a, creator=self.creator
        )
        self.cwc_b = ClassicWebsiteConfiguration.objects.create(
            collection=self.col_b, creator=self.creator
        )

    def _filtered_qs(self, user):
        qs = ClassicWebsiteConfiguration.objects.all()
        if user.is_superuser:
            return qs
        collection_ids = _get_user_collection_ids(user)
        if collection_ids.exists():
            return qs.filter(collection_id__in=collection_ids)
        return qs.none()

    def test_superuser_sees_all_classic_configs(self):
        qs = self._filtered_qs(self.superuser)
        self.assertIn(self.cwc_a, qs)
        self.assertIn(self.cwc_b, qs)

    def test_collection_team_member_sees_only_own_collection_config(self):
        qs = self._filtered_qs(self.collection_member)
        self.assertIn(self.cwc_a, qs)
        self.assertNotIn(self.cwc_b, qs)

    def test_non_collection_team_user_sees_nothing(self):
        qs = self._filtered_qs(self.other_user)
        self.assertEqual(qs.count(), 0)

