from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from collection.models import Collection, WebSiteConfiguration
from collection.wagtail_hooks import CollectionViewSet, WebSiteConfigurationViewSet
from files_storage.models import MinioConfiguration
from files_storage.wagtail_hooks import MinioConfigurationViewSet
from migration.models import ClassicWebsiteConfiguration
from migration.wagtail_hooks import ClassicWebsiteConfigurationViewSet
from team.models import CollectionTeamMember, TeamRole, get_user_membership_ids

User = get_user_model()


class CollectionTeamHelperFunctionsTest(TestCase):
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
        membership = get_user_membership_ids(self.active_member)
        self.assertIn(self.col.id, membership["collection_list_ids"])

    def test_get_user_collection_ids_excludes_inactive_memberships(self):
        membership = get_user_membership_ids(self.inactive_member)
        self.assertNotIn(self.col.id, membership["collection_list_ids"])

    def test_get_user_collection_ids_empty_for_non_member(self):
        membership = get_user_membership_ids(self.non_member)
        self.assertFalse(membership.get("collection_list_ids"))

    def test_is_collection_team_member_true_for_active(self):
        membership = get_user_membership_ids(self.active_member)
        self.assertTrue(membership.get("collection_list_ids"))

    def test_is_collection_team_member_false_for_inactive(self):
        membership = get_user_membership_ids(self.inactive_member)
        self.assertFalse(membership.get("collection_list_ids"))

    def test_is_collection_team_member_false_for_non_member(self):
        membership = get_user_membership_ids(self.non_member)
        self.assertFalse(membership.get("collection_list_ids"))


class CollectionViewSetQueryFilterTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
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
        self.viewset = CollectionViewSet()

    def _get_qs(self, user):
        request = self.factory.get("/admin/snippets/collection/collection/")
        request.user = user
        return self.viewset.get_queryset(request)

    def test_superuser_sees_all_collections(self):
        qs = self._get_qs(self.superuser)
        self.assertIn(self.col_a, qs)
        self.assertIn(self.col_b, qs)

    def test_collection_team_member_sees_only_own_collection(self):
        qs = self._get_qs(self.collection_member)
        self.assertIn(self.col_a, qs)
        self.assertNotIn(self.col_b, qs)

    def test_non_collection_team_user_sees_nothing(self):
        qs = self._get_qs(self.other_user)
        self.assertEqual(qs.count(), 0)


class WebSiteConfigurationQueryFilterTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
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
        self.viewset = WebSiteConfigurationViewSet()

    def _get_qs(self, user):
        request = self.factory.get("/admin/snippets/collection/websiteconfiguration/")
        request.user = user
        return self.viewset.get_queryset(request)

    def test_superuser_sees_all_website_configs(self):
        qs = self._get_qs(self.superuser)
        self.assertIn(self.ws_a, qs)
        self.assertIn(self.ws_b, qs)

    def test_collection_team_member_sees_only_own_collection_config(self):
        qs = self._get_qs(self.collection_member)
        self.assertIn(self.ws_a, qs)
        self.assertNotIn(self.ws_b, qs)

    def test_non_collection_team_user_sees_nothing(self):
        qs = self._get_qs(self.other_user)
        self.assertEqual(qs.count(), 0)


class MinioConfigurationQueryFilterTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="pass"
        )
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass"
        )
        self.collection_manager = User.objects.create_user(
            username="col_mgr", email="col_mgr@example.com", password="pass"
        )
        self.other_user = User.objects.create_user(
            username="other", email="other@example.com", password="pass"
        )
        self.col = Collection.objects.create(acron="A", name="Collection A", creator=self.creator)
        CollectionTeamMember.objects.create(
            user=self.collection_manager,
            collection=self.col,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.creator,
        )
        self.minio = MinioConfiguration.objects.create(
            name="minio1", host="minio.example.com", bucket="root", creator=self.creator
        )
        self.viewset = MinioConfigurationViewSet()

    def _get_qs(self, user):
        request = self.factory.get("/admin/snippets/files_storage/minioconfiguration/")
        request.user = user
        return self.viewset.get_queryset(request)

    def test_superuser_sees_all_minio_configs(self):
        qs = self._get_qs(self.superuser)
        self.assertIn(self.minio, qs)

    def test_collection_manager_sees_no_minio_configs(self):
        qs = self._get_qs(self.collection_manager)
        self.assertEqual(qs.count(), 0)

    def test_non_collection_admin_user_sees_nothing(self):
        qs = self._get_qs(self.other_user)
        self.assertEqual(qs.count(), 0)


class ClassicWebsiteConfigurationQueryFilterTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
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
        self.viewset = ClassicWebsiteConfigurationViewSet()

    def _get_qs(self, user):
        request = self.factory.get("/admin/snippets/migration/classicwebsiteconfiguration/")
        request.user = user
        return self.viewset.get_queryset(request)

    def test_superuser_sees_all_classic_configs(self):
        qs = self._get_qs(self.superuser)
        self.assertIn(self.cwc_a, qs)
        self.assertIn(self.cwc_b, qs)

    def test_collection_team_member_sees_only_own_collection_config(self):
        qs = self._get_qs(self.collection_member)
        self.assertIn(self.cwc_a, qs)
        self.assertNotIn(self.cwc_b, qs)

    def test_non_collection_team_user_sees_nothing(self):
        qs = self._get_qs(self.other_user)
        self.assertEqual(qs.count(), 0)
