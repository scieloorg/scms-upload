from io import StringIO
from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import RequestFactory, TestCase
from django.urls import reverse
from wagtail.admin.widgets import ListingButton
from wagtail.snippets.views.snippets import SnippetViewSet

from collection.models import Collection
from core.users.permission_policies import TeamScopedSnippetViewSetMixin
from journal.models import Journal, JournalCollection, OfficialJournal
from team.management.commands.create_user_groups import (
    Command as CreateUserGroupsCommand,
)
from team.models import (
    CollectionTeamMember,
    Company,
    CompanyTeamMember,
    JournalCompanyContract,
    TeamRole,
)
from upload.admin_buttons import get_package_action_buttons
from upload.models import Package, PackageZip, choices
from upload.querysets import get_scoped_package_queryset
from upload.wagtail_hooks import (
    PackageViewSet,
    PackageZipViewSet,
    QualityAnalysisPackageViewSet,
)

User = get_user_model()


class PackageScopingTest(TestCase):
    def setUp(self):
        CreateUserGroupsCommand().handle(stdout=StringIO(), sync_users=False)
        self.factory = RequestFactory()

        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        self.analyst_user = User.objects.create_user(
            username="analyst", email="analyst@example.com", password="password"
        )
        self.company_user = User.objects.create_user(
            username="provider",
            email="provider@example.com",
            password="password",
            is_staff=True,
        )
        self.unrelated_user = User.objects.create_user(
            username="unrelated", email="unrelated@example.com", password="password"
        )

        self.collection = Collection.objects.create(
            acron="scl", name="SciELO Brazil", creator=self.superuser
        )
        CollectionTeamMember.objects.create(
            user=self.analyst_user,
            collection=self.collection,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )

        self.official_j1 = OfficialJournal.objects.create(
            title="Journal One", issn_electronic="1111-1111", creator=self.superuser
        )
        self.journal_1 = Journal.objects.create(
            official_journal=self.official_j1,
            journal_acron="J1",
            creator=self.superuser,
        )
        JournalCollection.objects.create(
            journal=self.journal_1, collection=self.collection, creator=self.superuser
        )

        self.official_j2 = OfficialJournal.objects.create(
            title="Journal Two", issn_electronic="2222-2222", creator=self.superuser
        )
        self.journal_2 = Journal.objects.create(
            official_journal=self.official_j2,
            journal_acron="J2",
            creator=self.superuser,
        )

        self.company = Company.objects.create(name="Alpha XML", creator=self.superuser)
        CompanyTeamMember.objects.create(
            user=self.company_user,
            company=self.company,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )
        JournalCompanyContract.objects.create(
            journal=self.journal_1,
            company=self.company,
            is_active=True,
            creator=self.superuser,
        )

        fake_file = SimpleUploadedFile("sample.zip", b"PK\x05\x06" + b"\x00" * 18)
        self.pkg_zip_1 = PackageZip.objects.create(
            name="pkg1",
            file=fake_file,
            creator=self.company_user,
        )

        self.package_1 = Package.objects.create(
            pkg_zip=self.pkg_zip_1,
            journal=self.journal_1,
            status=choices.PS_VALIDATED_WITH_ERRORS,
            creator=self.company_user,
            file=fake_file,
        )

        self.package_2 = Package.objects.create(
            journal=self.journal_2,
            status=choices.PS_VALIDATED_WITH_ERRORS,
            creator=self.unrelated_user,
            file=fake_file,
        )

    def test_analyst_sees_packages_in_collection(self):
        request = self.factory.get("/admin/snippets/upload/package/")
        request.user = self.analyst_user

        viewset = PackageViewSet()
        qs = viewset.get_queryset(request)

        self.assertIn(self.package_1, qs)
        self.assertNotIn(self.package_2, qs)

    def test_package_queryset_filters_by_package_zip_id(self):
        request = self.factory.get(
            "/admin/snippets/upload/package/",
            {"pkg_zip_id": self.pkg_zip_1.pk},
        )
        request.user = self.superuser

        qs = PackageViewSet().get_queryset(request)

        self.assertIn(self.package_1, qs)
        self.assertNotIn(self.package_2, qs)

    def test_company_user_sees_only_own_contracted_packages(self):
        request = self.factory.get("/admin/snippets/upload/package/")
        request.user = self.company_user

        viewset = PackageViewSet()
        qs = viewset.get_queryset(request)

        self.assertIn(self.package_1, qs)
        self.assertNotIn(self.package_2, qs)

    def test_user_without_contract_sees_no_packages(self):
        request = self.factory.get("/admin/snippets/upload/package/")
        request.user = self.unrelated_user

        viewset = PackageViewSet()
        qs = viewset.get_queryset(request)

        self.assertEqual(qs.count(), 0)

    def test_company_user_package_zip_scoping(self):
        request = self.factory.get("/admin/snippets/upload/packagezip/")
        request.user = self.company_user

        viewset = PackageZipViewSet()
        qs = viewset.get_queryset(request)

        self.assertEqual(qs.count(), 1)
        self.assertIn(self.pkg_zip_1, qs)

    def test_collection_member_sees_package_zip_from_scoped_package(self):
        request = self.factory.get("/admin/snippets/upload/packagezip/")
        request.user = self.analyst_user

        qs = PackageZipViewSet().get_queryset(request)

        self.assertIn(self.pkg_zip_1, qs)

    def test_package_deletion_is_denied_by_native_policy(self):
        viewset = PackageViewSet()

        self.assertFalse(
            viewset.permission_policy.user_has_permission(
                self.superuser,
                "delete",
            )
        )

        request = self.factory.get(
            f"/admin/snippets/upload/package/delete/{self.package_1.pk}/"
        )
        request.user = self.superuser

        with self.assertRaises(PermissionDenied):
            viewset.delete_view(request, pk=str(self.package_1.pk))

    def test_native_package_action_respects_state_and_permission(self):
        buttons = get_package_action_buttons(
            self.analyst_user,
            self.package_1,
            ListingButton,
        )

        self.assertEqual(len(buttons), 1)
        self.assertIsInstance(buttons[0], ListingButton)
        self.assertEqual(
            buttons[0].url,
            reverse("upload:assign") + f"?package_id={self.package_1.pk}",
        )

    @patch("upload.views.package_utils.get_languages", return_value=[])
    def test_package_inspect_renders_native_action_buttons(self, _get_languages):
        self.client.force_login(self.superuser)

        summary = {
            "is_validation_finished": True,
            "conclusion": "",
            "total_xml_warnings": 0,
            "total_xml_errors": 0,
            "total_validations": 0,
            "critical_errors": 0,
        }
        with patch.object(
            Package,
            "files_list",
            new_callable=PropertyMock,
            return_value={"files": []},
        ), patch.object(
            Package,
            "summary",
            new_callable=PropertyMock,
            return_value=summary,
        ):
            response = self.client.get(
                f"/admin/snippets/upload/package/inspect/{self.package_1.pk}/"
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("upload:finish_deposit") + f"?package_id={self.package_1.pk}",
        )
        self.assertContains(
            response,
            reverse("upload:assign") + f"?package_id={self.package_1.pk}",
        )

    def test_inactive_membership_denies_native_upload_policy(self):
        CollectionTeamMember.objects.filter(user=self.analyst_user).update(
            is_active_member=False
        )

        self.assertFalse(
            PackageViewSet().permission_policy.user_has_permission(
                self.analyst_user,
                "view",
            )
        )

    @patch("upload.models.Package.finish_deposit", return_value=True)
    def test_finish_deposit_requires_post_confirmation(self, finish_deposit):
        self.client.force_login(self.superuser)
        url = reverse("upload:finish_deposit")

        response = self.client.get(url, {"package_id": self.package_1.pk})

        self.assertEqual(response.status_code, 200)
        finish_deposit.assert_not_called()

        response = self.client.post(url, {"package_id": self.package_1.pk})

        self.assertEqual(response.status_code, 302)
        finish_deposit.assert_called_once()

    def test_archive_package_requires_post_confirmation(self):
        self.package_1.status = choices.PS_UNEXPECTED
        self.package_1.save(update_fields=["status"])
        self.client.force_login(self.superuser)
        url = reverse("upload:archive_package")

        response = self.client.get(url, {"package_id": self.package_1.pk})
        self.package_1.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.package_1.status, choices.PS_UNEXPECTED)

        response = self.client.post(url, {"package_id": self.package_1.pk})
        self.package_1.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.package_1.status, choices.PS_ARCHIVED)

    @patch("upload.views.task_republish_articles.delay")
    def test_republish_rejects_entire_selection_with_out_of_scope_package(self, delay):
        self.client.force_login(self.analyst_user)

        response = self.client.post(
            reverse("upload:republish_selected"),
            {
                "package_ids": f"{self.package_1.pk},{self.package_2.pk}",
                "website_kind": "QA",
            },
        )

        self.assertEqual(response.status_code, 302)
        delay.assert_not_called()

    @patch("upload.views.task_republish_articles.delay")
    def test_republish_schedules_only_authorized_selection(self, delay):
        self.analyst_user.refresh_from_db()
        self.assertTrue(self.analyst_user.has_perm("upload.republish_package"))
        self.assertIn(
            self.package_1,
            get_scoped_package_queryset(self.analyst_user),
        )
        self.client.force_login(self.analyst_user)

        response = self.client.post(
            reverse("upload:republish_selected"),
            {
                "package_ids": str(self.package_1.pk),
                "website_kind": "QA",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            "/admin/snippets/upload/readytopublishpackage/",
        )
        delay.assert_called_once_with(
            username=self.analyst_user.username,
            user_id=self.analyst_user.id,
            website_kind="QA",
            package_ids=[self.package_1.pk],
        )

    def test_unconfigured_viewset_raises_improperly_configured(self):
        class BadViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
            model = Package

        viewset = BadViewSet()
        request = self.factory.get("/admin/snippets/upload/package/")
        request.user = self.superuser

        with self.assertRaises(ImproperlyConfigured):
            viewset.get_queryset(request)

    def test_multiple_scoping_strategies_raises_improperly_configured(self):
        class ConflictedViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
            model = Package
            journal_field = "journal"
            allow_unscoped_queryset = True

        viewset = ConflictedViewSet()
        request = self.factory.get("/admin/snippets/upload/package/")
        request.user = self.superuser

        with self.assertRaises(ImproperlyConfigured):
            viewset.get_queryset(request)

    def test_allow_unscoped_queryset_succeeds(self):
        class GlobalViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
            model = Package
            allow_unscoped_queryset = True

        viewset = GlobalViewSet()
        request = self.factory.get("/admin/snippets/upload/package/")
        request.user = self.superuser

        qs = viewset.get_queryset(request)
        self.assertGreaterEqual(qs.count(), 2)

    def test_object_level_enforcement_raises_404_for_out_of_scope_object(self):
        package_ct = ContentType.objects.get_for_model(Package)
        for perm in Permission.objects.filter(content_type=package_ct):
            self.company_user.user_permissions.add(perm)

        class ScopedPackageViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
            model = Package
            journal_field = "journal"

        viewset = ScopedPackageViewSet()

        # Edit View
        request = self.factory.get(
            f"/admin/snippets/upload/package/edit/{self.package_2.pk}/"
        )
        request.user = self.company_user
        with self.assertRaises(Http404):
            viewset.edit_view(request, pk=str(self.package_2.pk))

        # Delete View
        request = self.factory.get(
            f"/admin/snippets/upload/package/delete/{self.package_2.pk}/"
        )
        request.user = self.company_user
        with self.assertRaises(Http404):
            viewset.delete_view(request, pk=str(self.package_2.pk))

        # Inspect View
        request = self.factory.get(
            f"/admin/snippets/upload/package/inspect/{self.package_2.pk}/"
        )
        request.user = self.company_user
        with self.assertRaises(Http404):
            viewset.inspect_view(request, pk=str(self.package_2.pk))

        # Copy View
        request = self.factory.get(
            f"/admin/snippets/upload/package/copy/{self.package_2.pk}/"
        )
        request.user = self.company_user
        with self.assertRaises(Http404):
            viewset.copy_view(request, pk=str(self.package_2.pk))

    def test_object_level_enforcement_allows_in_scope_object(self):
        package_ct = ContentType.objects.get_for_model(Package)
        for perm in Permission.objects.filter(content_type=package_ct):
            self.company_user.user_permissions.add(perm)

        class ScopedPackageViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
            model = Package
            journal_field = "journal"

        viewset = ScopedPackageViewSet()

        # In-scope inspect view execution succeeds
        request = self.factory.get(
            f"/admin/snippets/upload/package/inspect/{self.package_1.pk}/"
        )
        request.user = self.company_user
        response = viewset.inspect_view(request, pk=str(self.package_1.pk))
        self.assertEqual(response.status_code, 200)

    def test_actual_upload_custom_views_reject_out_of_scope_object(self):
        inspect_request = self.factory.get(
            f"/admin/snippets/upload/package/inspect/{self.package_2.pk}/"
        )
        inspect_request.user = self.company_user

        with self.assertRaises(Http404):
            PackageViewSet().inspect_view(
                inspect_request,
                pk=str(self.package_2.pk),
            )

        edit_request = self.factory.get(
            f"/admin/snippets/upload/qapackage/edit/{self.package_2.pk}/"
        )
        edit_request.user = self.company_user

        with self.assertRaises(Http404):
            QualityAnalysisPackageViewSet().edit_view(
                edit_request,
                pk=str(self.package_2.pk),
            )
