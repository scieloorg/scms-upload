from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.test import RequestFactory, TestCase

from collection.models import Collection
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
from upload.controller import _check_article_and_journal
from upload.models import Package, PackageZip, choices
from upload.permissions import ACCESS_ALL_PACKAGES
from upload.querysets import scope_package_queryset
from upload.wagtail_hooks import PackageViewSet

User = get_user_model()


class UploadJournalAuthorizationTest(TestCase):
    def setUp(self):
        CreateUserGroupsCommand().handle(stdout=StringIO(), sync_users=False)
        self.factory = RequestFactory()

        self.superuser = User.objects.create_superuser(
            username="admin_user", email="admin@example.com", password="password"
        )
        self.bn_editor = User.objects.create_user(
            username="bn_editor_user", email="bn_editor@example.com", password="password"
        )
        self.mr_editor = User.objects.create_user(
            username="mr_editor_user", email="mr_editor@example.com", password="password"
        )
        self.qa_analyst = User.objects.create_user(
            username="qa_analyst_user", email="qa_analyst@example.com", password="password"
        )
        self.company_user = User.objects.create_user(
            username="company_user", email="company@example.com", password="password"
        )
        self.unrelated_user = User.objects.create_user(
            username="unrelated_user", email="unrelated@example.com", password="password"
        )

        self.collection = Collection.objects.create(
            acron="scl", name="SciELO Brazil", creator=self.superuser
        )

        self.official_bn = OfficialJournal.objects.create(
            title="Biota Neotropica",
            issn_electronic="1676-0611",
            issn_print="1676-0603",
            creator=self.superuser,
        )
        self.journal_bn = Journal.objects.create(
            title="Biota Neotropica",
            official_journal=self.official_bn,
            creator=self.superuser,
        )
        JournalCollection.objects.create(
            journal=self.journal_bn,
            collection=self.collection,
            creator=self.superuser,
        )

        self.official_mr = OfficialJournal.objects.create(
            title="Materials Research",
            issn_electronic="1980-5373",
            issn_print="1516-1439",
            creator=self.superuser,
        )
        self.journal_mr = Journal.objects.create(
            title="Materials Research",
            official_journal=self.official_mr,
            creator=self.superuser,
        )
        JournalCollection.objects.create(
            journal=self.journal_mr,
            collection=self.collection,
            creator=self.superuser,
        )

        # bn_editor -> journal_bn
        JournalTeamMember.objects.create(
            user=self.bn_editor,
            journal=self.journal_bn,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )

        # mr_editor -> journal_mr
        JournalTeamMember.objects.create(
            user=self.mr_editor,
            journal=self.journal_mr,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )

        # qa_analyst -> collection (acesso a todos os journals da colecao)
        CollectionTeamMember.objects.create(
            user=self.qa_analyst,
            collection=self.collection,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )

        # company_user -> Company Alfa com contrato ativo para journal_bn
        self.company = Company.objects.create(
            name="Alfa XML", creator=self.superuser
        )
        CompanyTeamMember.objects.create(
            user=self.company_user,
            company=self.company,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )
        JournalCompanyContract.objects.create(
            company=self.company,
            journal=self.journal_bn,
            is_active=True,
            creator=self.superuser,
        )

        self.package_zip = PackageZip.objects.create(
            name="mr-pkg-zip",
            creator=self.bn_editor,
        )
        self.package = Package.objects.create(
            name="1516-1439-mr-29-e20250709",
            pkg_zip=self.package_zip,
            creator=self.bn_editor,
            status=choices.PS_SUBMITTED,
        )

    def _make_xml_with_pre_mock(self, journal_obj):
        mock_xml_with_pre = MagicMock()
        mock_xml_with_pre.filename = "1516-1439-mr-29-e20250709.xml"
        mock_xml_with_pre.xmltree = MagicMock()
        return mock_xml_with_pre

    @patch("upload.controller.UploadJournalDataChecker")
    @patch("upload.controller.pp.is_registered_xml_with_pre")
    @patch("upload.controller._check_package_is_expected")
    @patch("upload.controller.UploadIssueDataChecker.from_xmltree")
    def test_unauthorized_user_is_blocked_and_subsequent_checks_are_not_called(
        self,
        mock_issue_checker_from_xmltree,
        mock_check_package_is_expected,
        mock_is_registered_xml,
        mock_journal_checker_cls,
    ):
        mock_checker = MagicMock()
        mock_checker.check.side_effect = lambda resp: resp.update({"journal": self.journal_mr})
        mock_journal_checker_cls.from_xmltree.return_value = mock_checker

        mock_xml_with_pre = self._make_xml_with_pre_mock(self.journal_mr)

        # bn_editor tenta submeter pacote de mr
        response = _check_article_and_journal(
            self.package, mock_xml_with_pre, self.bn_editor
        )

        # Comportamento observável
        self.assertEqual(response.get("package_status"), choices.PS_UNEXPECTED)
        self.assertEqual(response.get("error_level"), choices.VALIDATION_RESULT_BLOCKING)
        self.assertIn("Materials Research", response.get("error_message"))
        self.assertIn("not authorized", response.get("error_message").lower())

        # Garantia de não execução das etapas posteriores
        mock_is_registered_xml.assert_not_called()
        mock_check_package_is_expected.assert_not_called()
        mock_issue_checker_from_xmltree.assert_not_called()

    @patch("upload.controller.UploadJournalDataChecker")
    @patch("upload.controller.pp.is_registered_xml_with_pre")
    @patch("upload.controller._check_package_is_expected")
    @patch("upload.controller.UploadIssueDataChecker.from_xmltree")
    def test_anonymous_and_none_user_are_blocked(
        self,
        mock_issue_checker_from_xmltree,
        mock_check_package_is_expected,
        mock_is_registered_xml,
        mock_journal_checker_cls,
    ):
        mock_checker = MagicMock()
        mock_checker.check.side_effect = lambda resp: resp.update({"journal": self.journal_mr})
        mock_journal_checker_cls.from_xmltree.return_value = mock_checker

        mock_xml_with_pre = self._make_xml_with_pre_mock(self.journal_mr)

        # user = None
        resp_none = _check_article_and_journal(
            self.package, mock_xml_with_pre, None
        )
        self.assertEqual(resp_none.get("package_status"), choices.PS_UNEXPECTED)
        self.assertEqual(resp_none.get("error_level"), choices.VALIDATION_RESULT_BLOCKING)

        # user = AnonymousUser()
        resp_anon = _check_article_and_journal(
            self.package, mock_xml_with_pre, AnonymousUser()
        )
        self.assertEqual(resp_anon.get("package_status"), choices.PS_UNEXPECTED)
        self.assertEqual(resp_anon.get("error_level"), choices.VALIDATION_RESULT_BLOCKING)

        mock_is_registered_xml.assert_not_called()
        mock_check_package_is_expected.assert_not_called()
        mock_issue_checker_from_xmltree.assert_not_called()

    @patch("upload.controller.UploadJournalDataChecker")
    @patch("upload.controller.pp.is_registered_xml_with_pre")
    @patch("upload.controller._check_package_is_expected")
    @patch("upload.controller.UploadIssueDataChecker")
    @patch("upload.controller._check_xml_and_registered_data_compatibility")
    @patch("upload.controller._archive_pending_correction_package")
    def test_authorized_users_proceed_to_validations(
        self,
        mock_archive,
        mock_compat,
        mock_issue_checker_cls,
        mock_check_package_is_expected,
        mock_is_registered_xml,
        mock_journal_checker_cls,
    ):
        mock_j_checker = MagicMock()
        mock_j_checker.check.side_effect = lambda resp: resp.update({"journal": self.journal_mr})
        mock_journal_checker_cls.from_xmltree.return_value = mock_j_checker

        mock_i_checker = MagicMock()
        mock_i_checker.check.side_effect = lambda resp: resp.update({"issue": MagicMock()})
        mock_issue_checker_cls.from_xmltree.return_value = mock_i_checker

        mock_is_registered_xml.return_value = {"registered": False}

        mock_xml_with_pre = self._make_xml_with_pre_mock(self.journal_mr)

        # 1. mr_editor submetendo mr -> Autorizado
        resp_mr = _check_article_and_journal(
            self.package, mock_xml_with_pre, self.mr_editor
        )
        self.assertEqual(resp_mr.get("package_status"), choices.PS_ENQUEUED_FOR_VALIDATION)

        # 2. qa_analyst submetendo mr -> Autorizado pela colecao
        resp_qa = _check_article_and_journal(
            self.package, mock_xml_with_pre, self.qa_analyst
        )
        self.assertEqual(resp_qa.get("package_status"), choices.PS_ENQUEUED_FOR_VALIDATION)

        # 3. superuser submetendo mr -> Autorizado
        resp_su = _check_article_and_journal(
            self.package, mock_xml_with_pre, self.superuser
        )
        self.assertEqual(resp_su.get("package_status"), choices.PS_ENQUEUED_FOR_VALIDATION)

    @patch("upload.controller.UploadJournalDataChecker")
    @patch("upload.controller.pp.is_registered_xml_with_pre")
    @patch("upload.controller._check_package_is_expected")
    @patch("upload.controller.UploadIssueDataChecker")
    @patch("upload.controller._check_xml_and_registered_data_compatibility")
    @patch("upload.controller._archive_pending_correction_package")
    def test_company_contract_user_authorized_for_contracted_journal(
        self,
        mock_archive,
        mock_compat,
        mock_issue_checker_cls,
        mock_check_package_is_expected,
        mock_is_registered_xml,
        mock_journal_checker_cls,
    ):
        mock_j_checker = MagicMock()
        mock_j_checker.check.side_effect = lambda resp: resp.update({"journal": self.journal_bn})
        mock_journal_checker_cls.from_xmltree.return_value = mock_j_checker

        mock_i_checker = MagicMock()
        mock_i_checker.check.side_effect = lambda resp: resp.update({"issue": MagicMock()})
        mock_issue_checker_cls.from_xmltree.return_value = mock_i_checker

        mock_is_registered_xml.return_value = {"registered": False}

        mock_xml_with_pre = self._make_xml_with_pre_mock(self.journal_bn)

        # company_user tem contrato com journal_bn -> Autorizado
        resp_comp = _check_article_and_journal(
            self.package, mock_xml_with_pre, self.company_user
        )
        self.assertEqual(resp_comp.get("package_status"), choices.PS_ENQUEUED_FOR_VALIDATION)


class RejectedPackageVisibilityTest(TestCase):
    def setUp(self):
        CreateUserGroupsCommand().handle(stdout=StringIO(), sync_users=False)
        self.factory = RequestFactory()

        self.superuser = User.objects.create_superuser(
            username="admin_user_2", email="admin2@example.com", password="password"
        )
        self.bn_editor = User.objects.create_user(
            username="bn_editor_vis", email="bn_vis@example.com", password="password"
        )
        self.mr_editor = User.objects.create_user(
            username="mr_editor_vis", email="mr_vis@example.com", password="password"
        )

        self.official_bn = OfficialJournal.objects.create(
            title="Biota Neotropica",
            issn_electronic="1676-0611",
            issn_print="1676-0603",
            creator=self.superuser,
        )
        self.journal_bn = Journal.objects.create(
            title="Biota Neotropica",
            official_journal=self.official_bn,
            creator=self.superuser,
        )

        self.official_mr = OfficialJournal.objects.create(
            title="Materials Research",
            issn_electronic="1980-5373",
            issn_print="1516-1439",
            creator=self.superuser,
        )
        self.journal_mr = Journal.objects.create(
            title="Materials Research",
            official_journal=self.official_mr,
            creator=self.superuser,
        )

        JournalTeamMember.objects.create(
            user=self.bn_editor,
            journal=self.journal_bn,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )

        # Pacote regular de MR criado por mr_editor
        self.mr_regular_pkg = Package.objects.create(
            name="mr-regular-pkg",
            journal=self.journal_mr,
            creator=self.mr_editor,
            status=choices.PS_PREVIEW,
        )

        # Pacote rejeitado de MR criado indevidamente por bn_editor
        self.bn_rejected_pkg = Package.objects.create(
            name="mr-rejected-pkg",
            journal=self.journal_mr,
            creator=self.bn_editor,
            status=choices.PS_UNEXPECTED,
            blocking_errors=1,
        )

    def test_sender_sees_own_rejected_package_but_not_others_of_foreign_journal(self):
        scoped = scope_package_queryset(Package.objects.all(), self.bn_editor)

        # bn_editor DEVE ver o seu próprio pacote rejeitado
        self.assertIn(self.bn_rejected_pkg, scoped)

        # bn_editor NÃO DEVE ver o pacote regular da mr
        self.assertNotIn(self.mr_regular_pkg, scoped)

    def test_sender_with_access_all_packages_sees_own_rejected_package(self):
        perm = Permission.objects.get(codename=ACCESS_ALL_PACKAGES)
        self.bn_editor.user_permissions.add(perm)

        scoped = scope_package_queryset(Package.objects.all(), self.bn_editor)

        # Mesmo com ACCESS_ALL_PACKAGES (que amplia acesso no escopo de suas revistas),
        # deve ver seu pacote rejeitado com status unexpected
        self.assertIn(self.bn_rejected_pkg, scoped)
        self.assertNotIn(self.mr_regular_pkg, scoped)

    def test_viewset_queryset_filters_correctly_for_sender(self):
        viewset = PackageViewSet()
        request = self.factory.get("/admin/snippets/upload/package/")
        request.user = self.bn_editor

        qs = viewset.get_queryset(request)

        self.assertIn(self.bn_rejected_pkg, qs)
        self.assertNotIn(self.mr_regular_pkg, qs)
