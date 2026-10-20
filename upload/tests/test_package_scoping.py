import json
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
from wagtail.snippets.views.snippets import SnippetViewSet

from article.models import Article
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
    JournalTeamMember,
    TeamRole,
)
from upload.filters import DocumentFilterSet
from upload.authorization import user_can_act_on_package
from upload.models import (
    Package,
    PackageZip,
    PkgValidationResult,
    ValidationReport,
    choices,
)
from upload.permissions import PUBLISH_PACKAGE, REQUEST_CORRECTION
from upload.querysets import get_scoped_package_queryset
from upload.wagtail_hooks import (
    ArchivedPackageViewSet,
    PackageViewSet,
    PackageZipViewSet,
    QualityAnalysisPackageViewSet,
    ReadyToPublishPackageViewSet,
    ValidationReportViewSet,
    ValidationViewSet,
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
        request = self.factory.get("/admin/upload/documents/")
        request.user = self.analyst_user

        viewset = PackageViewSet()
        qs = viewset.get_queryset(request)

        self.assertIn(self.package_1, qs)
        self.assertNotIn(self.package_2, qs)

    def test_package_queryset_filters_by_package_zip_id(self):
        request = self.factory.get(
            "/admin/upload/documents/",
            {"pkg_zip_id": self.pkg_zip_1.pk},
        )
        request.user = self.superuser

        qs = PackageViewSet().get_queryset(request)

        self.assertIn(self.package_1, qs)
        self.assertNotIn(self.package_2, qs)

    def test_company_user_sees_only_own_contracted_packages(self):
        request = self.factory.get("/admin/upload/documents/")
        request.user = self.company_user

        viewset = PackageViewSet()
        qs = viewset.get_queryset(request)

        self.assertIn(self.package_1, qs)
        self.assertNotIn(self.package_2, qs)

    def test_user_without_contract_sees_no_packages(self):
        request = self.factory.get("/admin/upload/documents/")
        request.user = self.unrelated_user

        viewset = PackageViewSet()
        qs = viewset.get_queryset(request)

        self.assertEqual(qs.count(), 0)

    def test_validation_reports_and_results_follow_package_scope(self):
        scoped_report = ValidationReport.objects.create(
            package=self.package_1,
            category=choices.VAL_CAT_XML_FORMAT,
            creator=self.superuser,
        )
        unrelated_report = ValidationReport.objects.create(
            package=self.package_2,
            category=choices.VAL_CAT_XML_FORMAT,
            creator=self.superuser,
        )
        scoped_result = PkgValidationResult(
            report=scoped_report,
            creator=self.superuser,
        )
        scoped_result.save()
        unrelated_result = PkgValidationResult(
            report=unrelated_report,
            creator=self.superuser,
        )
        unrelated_result.save()
        request = self.factory.get("/admin/snippets/upload/validationreport/")
        request.user = self.analyst_user

        report_queryset = ValidationReportViewSet().get_queryset(request)
        result_queryset = ValidationViewSet().get_queryset(request)

        self.assertIn(scoped_report, report_queryset)
        self.assertNotIn(unrelated_report, report_queryset)
        self.assertIn(scoped_result, result_queryset)
        self.assertNotIn(unrelated_result, result_queryset)

    def test_company_user_package_zip_scoping(self):
        request = self.factory.get("/admin/upload/submissions/")
        request.user = self.company_user

        viewset = PackageZipViewSet()
        qs = viewset.get_queryset(request)

        self.assertEqual(qs.count(), 1)
        self.assertIn(self.pkg_zip_1, qs)

    def test_collection_member_sees_package_zip_from_scoped_package(self):
        request = self.factory.get("/admin/upload/submissions/")
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

        request = self.factory.get(f"/admin/upload/documents/delete/{self.package_1.pk}/")
        request.user = self.superuser

        with self.assertRaises(PermissionDenied):
            viewset.delete_view(request, pk=str(self.package_1.pk))

    @patch("upload.views.package_utils.get_languages", return_value=[])
    @patch.object(Package, "files_list", new_callable=PropertyMock, return_value={"files": []})
    def test_package_inspect_renders_actions_for_administrator_and_analyst(self, _get_languages, _files_list):
        summary = {
            "is_validation_finished": True,
            "conclusion": "",
            "total_xml_warnings": 0,
            "total_xml_errors": 0,
            "total_validations": 0,
            "critical_errors": 0,
        }
        decisions_url = reverse(
            "wagtailsnippets_upload_readytopublishpackage:edit",
            args=[self.package_1.pk],
        )
        finish_url = (
            reverse("upload:finish_deposit") + f"?package_id={self.package_1.pk}"
        )

        with patch.object(
            Package,
            "summary",
            new_callable=PropertyMock,
            return_value=summary,
        ):
            for user in (self.superuser, self.analyst_user):
                with self.subTest(user=user.username):
                    self.client.force_login(user)
                    response = self.client.get(
                        f"/admin/upload/documents/inspect/{self.package_1.pk}/"
                    )

                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, decisions_url)
                    self.assertContains(response, finish_url)


    def test_decision_navigation_returns_to_documents(self):
        self.client.force_login(self.superuser)
        documents_url = reverse("wagtailsnippets_upload_package:list")

        for model in ("qapackage", "readytopublishpackage"):
            with self.subTest(model=model):
                response = self.client.get(
                    reverse(f"wagtailsnippets_upload_{model}:list")
                )
                self.assertRedirects(
                    response, documents_url, fetch_redirect_response=False
                )
                response = self.client.get(
                    reverse(
                        f"wagtailsnippets_upload_{model}:edit",
                        args=[self.package_1.pk],
                    )
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["view"].index_url_name,
                    "wagtailsnippets_upload_package:list",
                )

    def test_archive_navigation_opens_archived_document_queue(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("wagtailsnippets_upload_archivedpackage:list")
        )
        self.assertRedirects(
            response,
            reverse("wagtailsnippets_upload_package:list") + "?queue=archived",
            fetch_redirect_response=False,
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

    def test_republish_requires_post_confirmation(self):
        self.client.force_login(self.analyst_user)

        response = self.client.get(
            reverse("upload:republish_selected"),
            {"package_ids": str(self.package_1.pk)},
        )

        self.assertEqual(response.status_code, 200)

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
            "/admin/upload/decisions/",
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
        request = self.factory.get("/admin/upload/documents/")
        request.user = self.superuser

        with self.assertRaises(ImproperlyConfigured):
            viewset.get_queryset(request)

    def test_multiple_scoping_strategies_raises_improperly_configured(self):
        class ConflictedViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
            model = Package
            journal_field = "journal"
            allow_unscoped_queryset = True

        viewset = ConflictedViewSet()
        request = self.factory.get("/admin/upload/documents/")
        request.user = self.superuser

        with self.assertRaises(ImproperlyConfigured):
            viewset.get_queryset(request)

    def test_allow_unscoped_queryset_succeeds(self):
        class GlobalViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
            model = Package
            allow_unscoped_queryset = True

        viewset = GlobalViewSet()
        request = self.factory.get("/admin/upload/documents/")
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
        request = self.factory.get(f"/admin/upload/documents/edit/{self.package_2.pk}/")
        request.user = self.company_user
        with self.assertRaises(Http404):
            viewset.edit_view(request, pk=str(self.package_2.pk))

        # Delete View
        request = self.factory.get(f"/admin/upload/documents/delete/{self.package_2.pk}/")
        request.user = self.company_user
        with self.assertRaises(Http404):
            viewset.delete_view(request, pk=str(self.package_2.pk))

        # Inspect View
        request = self.factory.get(f"/admin/upload/documents/inspect/{self.package_2.pk}/")
        request.user = self.company_user
        with self.assertRaises(Http404):
            viewset.inspect_view(request, pk=str(self.package_2.pk))

        # Copy View
        request = self.factory.get(f"/admin/upload/documents/copy/{self.package_2.pk}/")
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
        request = self.factory.get(f"/admin/upload/documents/inspect/{self.package_1.pk}/")
        request.user = self.company_user
        response = viewset.inspect_view(request, pk=str(self.package_1.pk))
        self.assertEqual(response.status_code, 200)

    def test_actual_upload_custom_views_reject_out_of_scope_object(self):
        inspect_request = self.factory.get(
            f"/admin/upload/documents/inspect/{self.package_2.pk}/"
        )
        inspect_request.user = self.company_user

        with self.assertRaises(Http404):
            PackageViewSet().inspect_view(
                inspect_request,
                pk=str(self.package_2.pk),
            )

        edit_request = self.factory.get(
            f"/admin/upload/quality-review/edit/{self.package_2.pk}/"
        )
        edit_request.user = self.company_user

        with self.assertRaises(Http404):
            QualityAnalysisPackageViewSet().edit_view(
                edit_request,
                pk=str(self.package_2.pk),
            )

    def correction_form(self, user, responsible, decision=choices.PS_PENDING_CORRECTION):
        return ReadyToPublishPackageViewSet().get_form_class()(
            data={
                "qa_decision": decision,
                "qa_comment": "Corrigir a identificação da revista.",
                "correction_assignee": responsible.pk,
                "analyst": json.dumps({"pk": self.package_1.analyst_id}),
                "article": "null",
                "linked": "[]",
                "order": 0,
                "upload_proc_result-TOTAL_FORMS": "0",
                "upload_proc_result-INITIAL_FORMS": "0",
                "upload_proc_result-MIN_NUM_FORMS": "0",
                "upload_proc_result-MAX_NUM_FORMS": "1000",
            },
            instance=self.package_1,
            for_user=user,
        )

    def add_company_scope_outside_collection(self):
        self.analyst_user.is_staff = True
        self.analyst_user.save()
        company = Company.objects.create(name="Beta XML", creator=self.superuser)
        colleague = User.objects.create_user(username="beta_depositor")
        for user in (self.analyst_user, colleague):
            CompanyTeamMember.objects.create(
                user=user,
                company=company,
                creator=self.superuser,
            )
        JournalCompanyContract.objects.create(
            company=company,
            journal=self.journal_2,
            is_active=True,
            creator=self.superuser,
        )
        self.package_2.creator = colleague
        self.package_2.status = choices.PS_PREVIEW
        self.package_2.save()

        return colleague


    def test_collection_visibility_does_not_extend_to_other_company_documents(self):
        self.add_company_scope_outside_collection()
        other_company_package = Package.objects.create(
            journal=self.journal_2,
            creator=self.unrelated_user,
            status=choices.PS_PREVIEW,
        )

        scoped = get_scoped_package_queryset(self.analyst_user)
        self.assertIn(self.package_1, scoped)
        self.assertIn(self.package_2, scoped)
        self.assertNotIn(other_company_package, scoped)


    def test_mixed_roles_allow_corrections_but_reject_publication_in_company_scope(
        self,
    ):
        colleague = self.add_company_scope_outside_collection()
        self.assertTrue(
            user_can_act_on_package(self.analyst_user, PUBLISH_PACKAGE, self.package_1)
        )
        self.assertFalse(
            user_can_act_on_package(self.analyst_user, PUBLISH_PACKAGE, self.package_2)
        )
        self.client.force_login(self.analyst_user)
        url = f"/admin/upload/decisions/edit/{self.package_2.pk}/"
        data = self.correction_form(
            self.analyst_user, colleague, choices.PS_READY_TO_PUBLISH
        ).data

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("qa_decision", response.context["form"].errors)
        self.package_2.refresh_from_db()
        self.assertIsNone(self.package_2.qa_decision)

        data["qa_decision"] = choices.PS_PENDING_CORRECTION
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.package_2.refresh_from_db()
        self.assertEqual(self.package_2.status, choices.PS_PENDING_CORRECTION)
        self.assertEqual(self.package_2.assignee, colleague)


    def test_publication_rejects_linked_packages_and_articles_from_company_only_scope(
        self,
    ):
        self.add_company_scope_outside_collection()
        article = Article.objects.create(journal=self.journal_2, creator=self.superuser)
        for field, value in (
            ("article", json.dumps({"pk": article.pk})),
            ("linked", json.dumps([{"pk": self.package_2.pk}])),
        ):
            with self.subTest(field=field):
                form = self.correction_form(
                    self.analyst_user, self.analyst_user, choices.PS_READY_TO_PUBLISH
                )
                form.data[field] = value
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)


    def test_publication_permission_does_not_follow_a_journal_membership(self):
        JournalTeamMember.objects.create(
            user=self.analyst_user,
            journal=self.journal_2,
            role=TeamRole.MEMBER,
            creator=self.superuser,
        )
        self.assertIn(self.package_2, get_scoped_package_queryset(self.analyst_user))
        self.assertTrue(self.analyst_user.has_perm("upload.publish_package"))
        self.assertFalse(
            user_can_act_on_package(self.analyst_user, PUBLISH_PACKAGE, self.package_2)
        )
        self.assertTrue(
            user_can_act_on_package(
                self.analyst_user, REQUEST_CORRECTION, self.package_2
            )
        )


    def test_direct_permission_does_not_replace_a_role_authorized_for_the_journal(self):
        self.company_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="upload",
                codename=PUBLISH_PACKAGE,
            )
        )
        user = User.objects.get(pk=self.company_user.pk)
        self.assertTrue(user.has_perm("upload.publish_package"))
        self.assertFalse(user_can_act_on_package(user, PUBLISH_PACKAGE, self.package_1))


    def test_correction_is_assigned_to_company_colleague_and_stays_active(self):
        colleague = User.objects.create_user(username="colleague")
        CompanyTeamMember.objects.create(
            user=colleague,
            company=self.company,
            creator=self.superuser,
            is_active_member=True,
        )
        self.package_1.analyst = CollectionTeamMember.objects.get(user=self.analyst_user)
        self.package_1.save()
        form = self.correction_form(self.analyst_user, colleague)
        form.data["order"] = "999"
        form.data["force_journal_publication"] = "on"
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["order"], self.package_1.order)
        self.assertFalse(form.cleaned_data["force_journal_publication"])
        package = form.save_all(self.analyst_user)
        self.assertTrue(package.process_qa_decision(self.analyst_user))
        package.refresh_from_db()
        self.assertEqual(package.assignee, colleague)
        self.assertEqual(package.analyst.user, self.analyst_user)
        self.assertEqual(package.status, choices.PS_PENDING_CORRECTION)
        request = self.factory.get("/")
        request.user = colleague
        self.assertIn(package, PackageViewSet().get_queryset(request))
        request.user = self.analyst_user
        self.assertNotIn(package, QualityAnalysisPackageViewSet().get_queryset(request))
        self.assertNotIn(package, ArchivedPackageViewSet().get_queryset(request))

    def test_company_member_can_request_correction_but_cannot_publish(self):
        self.package_1.analyst = CollectionTeamMember.objects.get(user=self.analyst_user)
        self.package_1.save()
        form = self.correction_form(self.company_user, self.company_user)
        self.assertTrue(form.is_valid(), form.errors)
        form = self.correction_form(
            self.company_user,
            self.company_user,
            choices.PS_READY_TO_PUBLISH,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("qa_decision", form.errors)

        self.package_1.refresh_from_db()
        self.package_1.status = choices.PS_PREVIEW
        self.package_1.save()
        self.client.force_login(self.company_user)
        url = f"/admin/upload/decisions/edit/{self.package_1.pk}/"
        response = self.client.post(url, form.data)
        self.assertEqual(response.status_code, 200)
        self.package_1.refresh_from_db()
        self.assertEqual(self.package_1.status, choices.PS_PREVIEW)
        self.assertIsNone(self.package_1.qa_decision)
        form = self.correction_form(self.company_user, self.company_user)
        response = self.client.post(url, form.data)
        self.assertEqual(response.status_code, 302)
        self.package_1.refresh_from_db()
        self.assertEqual(self.package_1.status, choices.PS_PENDING_CORRECTION)
        self.assertEqual(self.package_1.assignee, self.company_user)
        self.assertEqual(self.package_1.updated_by, self.company_user)

    def test_correction_rejects_recipient_outside_company_and_missing_reason(self):
        form = self.correction_form(self.analyst_user, self.unrelated_user)
        form.data["qa_comment"] = " "
        self.assertFalse(form.is_valid())
        self.assertIn("correction_assignee", form.errors)
        self.assertIn("qa_comment", form.errors)

    def test_company_review_does_not_expose_another_companys_documents(self):
        other_company = Company.objects.create(name="Other", creator=self.superuser)
        CompanyTeamMember.objects.create(
            company=other_company,
            user=self.unrelated_user,
            is_active_member=True,
            creator=self.superuser,
        )
        JournalCompanyContract.objects.create(
            company=other_company,
            journal=self.journal_1,
            is_active=True,
            creator=self.superuser,
        )
        self.package_2.journal = self.journal_1
        self.package_2.save()
        self.assertNotIn(self.package_2, get_scoped_package_queryset(self.company_user))
        form = self.correction_form(self.company_user, self.unrelated_user)
        self.assertFalse(form.is_valid())
        self.assertIn("correction_assignee", form.errors)

    def test_pending_correction_can_be_reassigned_with_decision_history(self):
        form = self.correction_form(self.company_user, self.company_user)
        self.assertTrue(form.is_valid(), form.errors)
        package = form.save_all(self.company_user)
        package.process_qa_decision(self.company_user)
        original = package.upload_proc_result.get(name="process_qa_decision")
        self.package_1.refresh_from_db()
        form = self.correction_form(self.analyst_user, self.company_user)
        form.data["qa_comment"] = "Conferir também as referências."
        self.assertTrue(form.is_valid(), form.errors)
        package = form.save_all(self.analyst_user)
        package.process_qa_decision(self.analyst_user)
        original.refresh_from_db()
        self.assertEqual(original.detail["comment"], "Corrigir a identificação da revista.")
        self.assertEqual(
            package.upload_proc_result.filter(name="process_qa_decision").count(), 2
        )
        self.client.force_login(self.company_user)
        response = self.client.get(f"/admin/upload/decisions/edit/{package.pk}/")
        self.assertEqual(response.status_code, 200)

    def test_document_queues_count_only_visible_documents(self):
        self.package_1.status = choices.PS_PENDING_CORRECTION
        self.package_1.assignee = self.company_user
        self.package_1.save()
        self.client.force_login(self.company_user)
        response = self.client.get("/admin/upload/documents/?queue=mine")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["object_list"]), [self.package_1])
        counts = {
            str(item["label"]): item["count"]
            for item in response.context["document_queues"]
        }
        self.assertEqual(max(counts.values()), 1)
        self.package_1.status = choices.PS_ARCHIVED
        self.package_1.save()
        response = self.client.get("/admin/upload/documents/")
        self.assertEqual(list(response.context["object_list"]), [])
        response = self.client.get("/admin/upload/documents/?queue=archived")
        self.assertEqual(list(response.context["object_list"]), [self.package_1])

    def test_review_can_be_delegated_to_journal_member_without_publication_right(self):
        reviewer = User.objects.create_user(username="journal_reviewer", is_staff=True)
        JournalTeamMember.objects.create(
            user=reviewer,
            journal=self.journal_1,
            creator=self.superuser,
            is_active_member=True,
        )
        form = self.correction_form(
            self.company_user, self.company_user, choices.PS_PENDING_QA_DECISION
        )
        form.data["reviewer"] = reviewer.pk
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save_all(self.company_user)
        saved.process_qa_decision(self.company_user)
        saved.refresh_from_db()
        self.assertEqual(saved.assignee, reviewer)
        self.assertEqual(saved.status, choices.PS_PENDING_QA_DECISION)
        self.assertFalse(reviewer.has_perm("upload.publish_package"))
        self.assertIn(saved, get_scoped_package_queryset(reviewer))
        form = self.correction_form(
            self.company_user, self.company_user, choices.PS_PENDING_QA_DECISION
        )
        form.data["reviewer"] = self.unrelated_user.pk
        self.assertFalse(form.is_valid())
        self.assertIn("reviewer", form.errors)

    def test_document_status_filter_matches_display_and_includes_archived(self):
        self.client.force_login(self.company_user)
        self.package_1.status = choices.PS_PREVIEW
        self.package_1.qa_ws_status = choices.PUBLISHED
        self.package_1.public_ws_status = choices.UNRELEASED
        self.package_1.save()
        url = reverse("wagtailsnippets_upload_package:list")

        response = self.client.get(url, {"status": choices.PS_PREVIEW})
        self.assertEqual(list(response.context["object_list"]), [self.package_1])
        status_field = DocumentFilterSet().form.fields["status"]
        self.assertEqual(
            str(dict(status_field.choices)[choices.PS_PREVIEW]),
            str(self.package_1.work_situation()),
        )
        self.assertEqual(
            str(status_field.label),
            str(Package.work_situation.short_description),
        )
        response = self.client.get(
            url,
            {
                "qa_ws_status": choices.PUBLISHED,
                "public_ws_status": choices.UNRELEASED,
            },
        )
        self.assertEqual(list(response.context["object_list"]), [self.package_1])
        response = self.client.get(url, {"public_ws_status": choices.PUBLISHED})
        self.assertEqual(list(response.context["object_list"]), [])

        self.package_1.status = choices.PS_ARCHIVED
        self.package_1.save()
        response = self.client.get(url, {"status": choices.PS_ARCHIVED})
        self.assertEqual(list(response.context["object_list"]), [self.package_1])
        self.assertNotIn(self.package_2, response.context["object_list"])
        response = self.client.get(url)
        self.assertEqual(list(response.context["object_list"]), [])

    def test_document_error_filters_select_presence_instead_of_exact_count(self):
        self.client.force_login(self.company_user)
        self.package_1.blocking_errors = 2
        self.package_1.critical_errors = 3
        self.package_1.save()
        url = reverse("wagtailsnippets_upload_package:list")

        for field in ("blocking_errors", "critical_errors"):
            with self.subTest(field=field):
                response = self.client.get(url, {field: "true"})
                self.assertEqual(list(response.context["object_list"]), [self.package_1])
                response = self.client.get(url, {field: "false"})
                self.assertEqual(list(response.context["object_list"]), [])

    def test_package_name_filter_is_partial_and_respects_scope(self):
        self.client.force_login(self.company_user)
        response = self.client.get("/admin/upload/documents/", {"package": "pkg"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["object_list"]), [self.package_1])
        response = self.client.get("/admin/upload/documents/", {"package": "missing"})
        self.assertEqual(list(response.context["object_list"]), [])

    def test_submission_filters_use_dates_and_document_presence_within_scope(self):
        self.client.force_login(self.company_user)
        empty = PackageZip.objects.create(name="empty", creator=self.company_user)
        url = "/admin/upload/submissions/"
        response = self.client.get(url, {"has_documents": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["object_list"]), [self.pkg_zip_1])
        response = self.client.get(url, {"has_documents": "false"})
        self.assertEqual(list(response.context["object_list"]), [empty])
        response = self.client.get(url, {"created_from": "2099-01-01"})
        self.assertEqual(list(response.context["object_list"]), [])
