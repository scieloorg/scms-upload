from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from collection.models import Collection
from journal.models import Journal
from team.models import (
    CollectionTeamMember,
    Company,
    CompanyTeamMember,
    JournalCompanyContract,
    JournalTeamMember,
    TeamRole,
)

User = get_user_model()


class CollectionTeamMemberModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.manager_user = User.objects.create_user(
            username="manager", email="manager@example.com", password="testpass123"
        )
        self.collection = Collection.objects.create(
            acron="TST",
            name="Test Collection",
            creator=self.user,
        )

    def test_create_collection_team_member(self):
        member = CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertEqual(member.user, self.user)
        self.assertEqual(member.collection, self.collection)
        self.assertEqual(member.role, TeamRole.MEMBER)

    def test_collection_team_member_unique_together(self):
        CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            role=TeamRole.MEMBER,
            creator=self.user,
        )
        with self.assertRaises(IntegrityError):
            CollectionTeamMember.objects.create(
                user=self.user,
                collection=self.collection,
                role=TeamRole.MANAGER,
                creator=self.user,
            )

    def test_default_role_is_member(self):
        member = CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            is_active_member=True,
            creator=self.user,
        )
        self.assertEqual(member.role, TeamRole.MEMBER)

    def test_autocomplete_label_includes_role(self):
        member = CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            role=TeamRole.MEMBER,
            creator=self.user,
        )
        label = member.autocomplete_label()
        self.assertIn("Member", label)
        self.assertIn(str(self.user), label)
        self.assertIn(str(self.collection), label)

    def test_str_includes_role(self):
        manager = CollectionTeamMember.objects.create(
            user=self.manager_user,
            collection=self.collection,
            role=TeamRole.MANAGER,
            creator=self.user,
        )
        str_repr = str(manager)
        self.assertIn("Manager", str_repr)
        self.assertIn(str(self.manager_user), str_repr)


class CompanyModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_create_company(self):
        company = Company.objects.create(
            name="Test Company",
            description="A test company",
            contact_email="contact@testcompany.com",
            contact_phone="+55 11 1234-5678",
            is_active=True,
            creator=self.user,
        )
        self.assertEqual(company.name, "Test Company")
        self.assertTrue(company.is_active)
        self.assertEqual(str(company), "Test Company")

    def test_company_unique_name(self):
        Company.objects.create(
            name="Unique Company",
            creator=self.user,
        )
        with self.assertRaises(IntegrityError):
            Company.objects.create(
                name="Unique Company",
                creator=self.user,
            )

    def test_company_autocomplete_label(self):
        company = Company.objects.create(
            name="Test Company",
            creator=self.user,
        )
        self.assertEqual(company.autocomplete_label(), "Test Company")

    def test_company_with_visual_identity(self):
        company = Company.objects.create(
            name="Certified Company",
            url="https://example.com",
            personal_contact="John Doe",
            certified_since=date(2020, 1, 1),
            creator=self.user,
        )
        self.assertEqual(company.url, "https://example.com")
        self.assertEqual(company.personal_contact, "John Doe")
        self.assertEqual(company.certified_since, date(2020, 1, 1))


class JournalTeamMemberModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.journal = Journal.objects.create(
            title="Test Journal",
            creator=self.user,
        )

    def test_create_journal_team_member(self):
        member = JournalTeamMember.objects.create(
            user=self.user,
            journal=self.journal,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertEqual(member.user, self.user)
        self.assertEqual(member.journal, self.journal)
        self.assertEqual(member.role, TeamRole.MEMBER)

    def test_journal_team_member_unique_together(self):
        JournalTeamMember.objects.create(
            user=self.user,
            journal=self.journal,
            role=TeamRole.MEMBER,
            creator=self.user,
        )
        with self.assertRaises(IntegrityError):
            JournalTeamMember.objects.create(
                user=self.user,
                journal=self.journal,
                role=TeamRole.MANAGER,
                creator=self.user,
            )


class CompanyTeamMemberModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.company = Company.objects.create(
            name="Test Company",
            creator=self.user,
        )

    def test_create_company_team_member(self):
        member = CompanyTeamMember.objects.create(
            user=self.user,
            company=self.company,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertEqual(member.user, self.user)
        self.assertEqual(member.company, self.company)
        self.assertEqual(member.role, TeamRole.MEMBER)

    def test_company_team_member_unique_together(self):
        CompanyTeamMember.objects.create(
            user=self.user,
            company=self.company,
            role=TeamRole.MEMBER,
            creator=self.user,
        )
        with self.assertRaises(IntegrityError):
            CompanyTeamMember.objects.create(
                user=self.user,
                company=self.company,
                role=TeamRole.MANAGER,
                creator=self.user,
            )


class JournalCompanyContractModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.journal = Journal.objects.create(
            title="Test Journal",
            creator=self.user,
        )
        self.company = Company.objects.create(
            name="Test Company",
            creator=self.user,
        )

    def test_create_contract(self):
        contract = JournalCompanyContract.objects.create(
            journal=self.journal,
            company=self.company,
            is_active=True,
            notes="Test contract",
            creator=self.user,
        )
        self.assertEqual(contract.journal, self.journal)
        self.assertEqual(contract.company, self.company)
        self.assertTrue(contract.is_active)
        self.assertIn(str(self.journal), str(contract))
        self.assertIn(str(self.company), str(contract))

    def test_contract_unique_together(self):
        JournalCompanyContract.objects.create(
            journal=self.journal,
            company=self.company,
            creator=self.user,
        )
        with self.assertRaises(IntegrityError):
            JournalCompanyContract.objects.create(
                journal=self.journal,
                company=self.company,
                creator=self.user,
            )
