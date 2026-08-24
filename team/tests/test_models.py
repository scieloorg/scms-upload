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
    """Test cases for the CollectionTeamMember model."""

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
        """Test creating a collection team member."""
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
        self.assertFalse(member.is_manager())

    def test_create_collection_team_manager(self):
        """Test creating a collection team manager."""
        manager = CollectionTeamMember.objects.create(
            user=self.manager_user,
            collection=self.collection,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertEqual(manager.role, TeamRole.MANAGER)
        self.assertTrue(manager.is_manager())

    def test_collection_team_member_unique_together(self):
        """Test that a user can only be added once to a collection."""
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

    def test_user_is_manager(self):
        """Test checking if a user is a collection manager."""
        CollectionTeamMember.objects.create(
            user=self.manager_user,
            collection=self.collection,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertTrue(
            CollectionTeamMember.user_is_manager(self.manager_user, self.collection)
        )
        self.assertFalse(CollectionTeamMember.user_is_manager(self.user, self.collection))

    def test_get_user_collections(self):
        """Test getting collections for a user."""
        CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        collections = CollectionTeamMember.get_user_collections(self.user)
        self.assertEqual(collections.count(), 1)
        self.assertEqual(collections.first().collection, self.collection)

    def test_collection_get_managers(self):
        """Test getting managers for a collection."""
        CollectionTeamMember.objects.create(
            user=self.manager_user,
            collection=self.collection,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        managers = Collection.get_managers(self.collection.id)
        self.assertEqual(managers.count(), 1)
        self.assertEqual(managers.first().user, self.manager_user)

    def test_collection_get_members(self):
        """Test getting all members (including managers) for a collection."""
        CollectionTeamMember.objects.create(
            user=self.manager_user,
            collection=self.collection,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        members = Collection.get_members(self.collection.id)
        self.assertEqual(members.count(), 2)

    def test_default_role_is_member(self):
        """Test that the default role is MEMBER."""
        member = CollectionTeamMember.objects.create(
            user=self.user,
            collection=self.collection,
            is_active_member=True,
            creator=self.user,
        )
        self.assertEqual(member.role, TeamRole.MEMBER)

    def test_autocomplete_label_includes_role(self):
        """Test that autocomplete label includes role."""
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
        """Test that string representation includes role."""
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
    """Test cases for the Company model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_create_company(self):
        """Test creating a company."""
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
        """Test that company names must be unique."""
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
        """Test company autocomplete label."""
        company = Company.objects.create(
            name="Test Company",
            creator=self.user,
        )
        self.assertEqual(company.autocomplete_label(), "Test Company")

    def test_company_with_visual_identity(self):
        """Test creating a company with url, logo, certified_since, and personal_contact."""
        from datetime import date
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
    """Test cases for the JournalTeamMember model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.manager_user = User.objects.create_user(
            username="manager", email="manager@example.com", password="testpass123"
        )
        # Create a minimal journal for testing
        self.journal = Journal.objects.create(
            title="Test Journal",
            creator=self.user,
        )

    def test_create_journal_team_member(self):
        """Test creating a journal team member."""
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
        self.assertFalse(member.is_manager())

    def test_create_journal_team_manager(self):
        """Test creating a journal team manager."""
        manager = JournalTeamMember.objects.create(
            user=self.manager_user,
            journal=self.journal,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertEqual(manager.role, TeamRole.MANAGER)
        self.assertTrue(manager.is_manager())

    def test_journal_team_member_unique_together(self):
        """Test that a user can only be added once to a journal."""
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

    def test_user_is_manager(self):
        """Test checking if a user is a journal manager."""
        JournalTeamMember.objects.create(
            user=self.manager_user,
            journal=self.journal,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertTrue(
            JournalTeamMember.user_is_manager(self.manager_user, self.journal)
        )
        self.assertFalse(JournalTeamMember.user_is_manager(self.user, self.journal))

    def test_get_user_journals(self):
        """Test getting journals for a user."""
        JournalTeamMember.objects.create(
            user=self.user,
            journal=self.journal,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        journals = JournalTeamMember.get_user_journals(self.user)
        self.assertEqual(journals.count(), 1)
        self.assertEqual(journals.first().journal, self.journal)


class CompanyTeamMemberModelTest(TestCase):
    """Test cases for the CompanyTeamMember model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.manager_user = User.objects.create_user(
            username="manager", email="manager@example.com", password="testpass123"
        )
        self.company = Company.objects.create(
            name="Test Company",
            creator=self.user,
        )

    def test_create_company_team_member(self):
        """Test creating a company team member."""
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
        self.assertFalse(member.is_manager())

    def test_create_company_team_manager(self):
        """Test creating a company team manager."""
        manager = CompanyTeamMember.objects.create(
            user=self.manager_user,
            company=self.company,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertEqual(manager.role, TeamRole.MANAGER)
        self.assertTrue(manager.is_manager())

    def test_company_team_member_unique_together(self):
        """Test that a user can only be added once to a company."""
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

    def test_user_is_manager(self):
        """Test checking if a user is a company manager."""
        CompanyTeamMember.objects.create(
            user=self.manager_user,
            company=self.company,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertTrue(
            CompanyTeamMember.user_is_manager(self.manager_user, self.company)
        )
        self.assertFalse(CompanyTeamMember.user_is_manager(self.user, self.company))

    def test_get_user_companies(self):
        """Test getting companies for a user."""
        CompanyTeamMember.objects.create(
            user=self.user,
            company=self.company,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        companies = CompanyTeamMember.get_user_companies(self.user)
        self.assertEqual(companies.count(), 1)
        self.assertEqual(companies.first().company, self.company)

    def test_company_get_managers(self):
        """Test getting managers for a company."""
        CompanyTeamMember.objects.create(
            user=self.manager_user,
            company=self.company,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        CompanyTeamMember.objects.create(
            user=self.user,
            company=self.company,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        managers = Company.get_managers(self.company.id)
        self.assertEqual(managers.count(), 1)
        self.assertEqual(managers.first().user, self.manager_user)

    def test_company_get_members(self):
        """Test getting all members (including managers) for a company."""
        CompanyTeamMember.objects.create(
            user=self.manager_user,
            company=self.company,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        CompanyTeamMember.objects.create(
            user=self.user,
            company=self.company,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        members = Company.get_members(self.company.id)
        self.assertEqual(members.count(), 2)


class JournalCompanyContractModelTest(TestCase):
    """Test cases for the JournalCompanyContract model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.manager_user = User.objects.create_user(
            username="manager", email="manager@example.com", password="testpass123"
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
        """Test creating a journal-company contract."""
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
        """Test that a journal-company pair must be unique."""
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

    def test_get_journal_companies(self):
        """Test getting companies contracted by a journal."""
        JournalCompanyContract.objects.create(
            journal=self.journal,
            company=self.company,
            is_active=True,
            creator=self.user,
        )
        contracts = JournalCompanyContract.get_journal_companies(self.journal)
        self.assertEqual(contracts.count(), 1)
        self.assertEqual(contracts.first().company, self.company)

    def test_get_company_journals(self):
        """Test getting journals that contracted a company."""
        JournalCompanyContract.objects.create(
            journal=self.journal,
            company=self.company,
            is_active=True,
            creator=self.user,
        )
        contracts = JournalCompanyContract.get_company_journals(self.company)
        self.assertEqual(contracts.count(), 1)
        self.assertEqual(contracts.first().journal, self.journal)

    def test_can_manage_contract_as_manager(self):
        """Test that journal managers can manage contracts."""
        JournalTeamMember.objects.create(
            user=self.manager_user,
            journal=self.journal,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertTrue(
            JournalCompanyContract.can_manage_contract(self.manager_user, self.journal)
        )

    def test_can_manage_contract_as_non_manager(self):
        """Test that non-managers cannot manage contracts."""
        JournalTeamMember.objects.create(
            user=self.user,
            journal=self.journal,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.user,
        )
        self.assertFalse(
            JournalCompanyContract.can_manage_contract(self.user, self.journal)
        )
