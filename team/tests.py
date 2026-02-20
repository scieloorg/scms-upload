from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import RequestFactory, TestCase

from collection.models import Collection
from journal.models import Journal
from team.models import (
    COLLECTION_TEAM_ADMIN,
    COLLECTION_TEAM_MEMBER,
    COMPANY_MEMBER,
    COMPANY_TEAM_ADMIN,
    GROUP_NAMES,
    JOURNAL_TEAM_ADMIN,
    JOURNAL_TEAM_MEMBER,
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


class GroupNamesTest(TestCase):
    """Test that group name constants are defined correctly."""

    def test_group_names_constants(self):
        """Test that all group name constants are defined."""
        self.assertEqual(COLLECTION_TEAM_ADMIN, "COLLECTION_TEAM_ADMIN")
        self.assertEqual(COLLECTION_TEAM_MEMBER, "COLLECTION_TEAM_MEMBER")
        self.assertEqual(JOURNAL_TEAM_ADMIN, "JOURNAL_TEAM_ADMIN")
        self.assertEqual(JOURNAL_TEAM_MEMBER, "JOURNAL_TEAM_MEMBER")
        self.assertEqual(COMPANY_TEAM_ADMIN, "COMPANY_TEAM_ADMIN")
        self.assertEqual(COMPANY_MEMBER, "COMPANY_MEMBER")

    def test_group_names_list(self):
        """Test that GROUP_NAMES contains all expected group names."""
        self.assertIn(COLLECTION_TEAM_ADMIN, GROUP_NAMES)
        self.assertIn(COLLECTION_TEAM_MEMBER, GROUP_NAMES)
        self.assertIn(JOURNAL_TEAM_ADMIN, GROUP_NAMES)
        self.assertIn(JOURNAL_TEAM_MEMBER, GROUP_NAMES)
        self.assertIn(COMPANY_TEAM_ADMIN, GROUP_NAMES)
        self.assertIn(COMPANY_MEMBER, GROUP_NAMES)
        self.assertEqual(len(GROUP_NAMES), 6)


class GetQuerysetFilteringTest(TestCase):
    """Test the queryset filtering logic used in wagtail_hooks get_queryset methods."""

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="superuser", email="super@example.com", password="pass"
        )
        self.collection_manager = User.objects.create_user(
            username="col_manager", email="col_manager@example.com", password="pass"
        )
        self.collection_member = User.objects.create_user(
            username="col_member", email="col_member@example.com", password="pass"
        )
        self.journal_manager = User.objects.create_user(
            username="jour_manager", email="jour_manager@example.com", password="pass"
        )
        self.journal_member = User.objects.create_user(
            username="jour_member", email="jour_member@example.com", password="pass"
        )
        self.company_manager = User.objects.create_user(
            username="comp_manager", email="comp_manager@example.com", password="pass"
        )
        self.company_member_user = User.objects.create_user(
            username="comp_member", email="comp_member@example.com", password="pass"
        )

        self.collection = Collection.objects.create(
            acron="TST", name="Test Collection", creator=self.superuser
        )
        self.other_collection = Collection.objects.create(
            acron="OTH", name="Other Collection", creator=self.superuser
        )
        self.journal = Journal.objects.create(title="Test Journal", creator=self.superuser)
        self.other_journal = Journal.objects.create(title="Other Journal", creator=self.superuser)
        self.company = Company.objects.create(name="Test Company", creator=self.superuser)
        self.other_company = Company.objects.create(name="Other Company", creator=self.superuser)

        # Set up collection team members
        CollectionTeamMember.objects.create(
            user=self.collection_manager,
            collection=self.collection,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.superuser,
        )
        CollectionTeamMember.objects.create(
            user=self.collection_member,
            collection=self.collection,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )

        # Set up journal team members
        JournalTeamMember.objects.create(
            user=self.journal_manager,
            journal=self.journal,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.superuser,
        )
        JournalTeamMember.objects.create(
            user=self.journal_member,
            journal=self.journal,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )
        # journal_manager also member of other_journal (as member)
        JournalTeamMember.objects.create(
            user=self.journal_manager,
            journal=self.other_journal,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )

        # Set up company team members
        CompanyTeamMember.objects.create(
            user=self.company_manager,
            company=self.company,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.superuser,
        )
        CompanyTeamMember.objects.create(
            user=self.company_member_user,
            company=self.company,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.superuser,
        )

        # Contracts
        self.contract = JournalCompanyContract.objects.create(
            journal=self.journal,
            company=self.company,
            is_active=True,
            creator=self.superuser,
        )
        self.other_contract = JournalCompanyContract.objects.create(
            journal=self.other_journal,
            company=self.other_company,
            is_active=True,
            creator=self.superuser,
        )

    # --- CollectionTeamMember queryset filtering ---

    def test_collection_team_qs_superuser_sees_all(self):
        """Superuser should see all CollectionTeamMember records."""
        qs = CollectionTeamMember.objects.all()
        self.assertEqual(qs.count(), 2)

    def test_collection_team_qs_manager_sees_own_collection_members(self):
        """COLLECTION_TEAM_ADMIN sees members of their collection(s)."""
        managed_ids = CollectionTeamMember.objects.filter(
            user=self.collection_manager, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("collection", flat=True)
        filtered = CollectionTeamMember.objects.filter(collection__in=managed_ids)
        # Both manager and member of the collection should be visible
        self.assertEqual(filtered.count(), 2)

    def test_collection_team_qs_member_sees_only_self(self):
        """COLLECTION_TEAM_MEMBER sees only their own record."""
        managed_ids = CollectionTeamMember.objects.filter(
            user=self.collection_member, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("collection", flat=True)
        self.assertFalse(managed_ids.exists())
        # Falls back to filter(user=self.collection_member)
        filtered = CollectionTeamMember.objects.filter(user=self.collection_member)
        self.assertEqual(filtered.count(), 1)

    # --- Company queryset filtering ---

    def test_company_qs_collection_manager_sees_all(self):
        """COLLECTION_TEAM_ADMIN can see all companies."""
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=self.collection_manager, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        self.assertTrue(is_collection_manager)
        # Collection manager should see all companies
        qs = Company.objects.all()
        self.assertEqual(qs.count(), 2)

    def test_company_qs_company_member_sees_own(self):
        """Company member sees only their own companies."""
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=self.company_member_user, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        self.assertFalse(is_collection_manager)
        company_ids = CompanyTeamMember.objects.filter(
            user=self.company_member_user, is_active_member=True
        ).values_list("company", flat=True)
        filtered = Company.objects.filter(id__in=company_ids)
        self.assertEqual(filtered.count(), 1)
        self.assertEqual(filtered.first(), self.company)

    # --- JournalTeamMember queryset filtering ---

    def test_journal_team_qs_collection_manager_sees_all(self):
        """COLLECTION_TEAM_ADMIN sees all journal team members."""
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=self.collection_manager, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        self.assertTrue(is_collection_manager)
        # Should see all journal team members
        self.assertEqual(JournalTeamMember.objects.count(), 3)

    def test_journal_team_qs_journal_manager_sees_own_journal_members(self):
        """JOURNAL_TEAM_ADMIN sees members of their managed journals."""
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=self.journal_manager, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        self.assertFalse(is_collection_manager)
        managed_journal_ids = JournalTeamMember.objects.filter(
            user=self.journal_manager, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("journal", flat=True)
        self.assertTrue(managed_journal_ids.exists())
        filtered = JournalTeamMember.objects.filter(journal__in=managed_journal_ids)
        # journal_manager and journal_member are in the managed journal
        self.assertEqual(filtered.count(), 2)

    def test_journal_team_qs_journal_member_sees_only_self(self):
        """JOURNAL_TEAM_MEMBER sees only their own record."""
        managed_journal_ids = JournalTeamMember.objects.filter(
            user=self.journal_member, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("journal", flat=True)
        self.assertFalse(managed_journal_ids.exists())
        filtered = JournalTeamMember.objects.filter(user=self.journal_member)
        self.assertEqual(filtered.count(), 1)

    # --- CompanyTeamMember queryset filtering ---

    def test_company_team_qs_collection_manager_sees_all(self):
        """COLLECTION_TEAM_ADMIN sees all company team members."""
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=self.collection_manager, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        self.assertTrue(is_collection_manager)
        self.assertEqual(CompanyTeamMember.objects.count(), 2)

    def test_company_team_qs_manager_sees_own_company_members(self):
        """COMPANY_TEAM_ADMIN sees members of their managed companies."""
        managed_company_ids = CompanyTeamMember.objects.filter(
            user=self.company_manager, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("company", flat=True)
        self.assertTrue(managed_company_ids.exists())
        filtered = CompanyTeamMember.objects.filter(company__in=managed_company_ids)
        self.assertEqual(filtered.count(), 2)

    def test_company_team_qs_member_sees_only_self(self):
        """COMPANY_MEMBER sees only their own record."""
        managed_company_ids = CompanyTeamMember.objects.filter(
            user=self.company_member_user, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("company", flat=True)
        self.assertFalse(managed_company_ids.exists())
        filtered = CompanyTeamMember.objects.filter(user=self.company_member_user)
        self.assertEqual(filtered.count(), 1)

    # --- JournalCompanyContract queryset filtering ---

    def test_contract_qs_collection_manager_sees_all(self):
        """COLLECTION_TEAM_ADMIN sees all contracts."""
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=self.collection_manager, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        self.assertTrue(is_collection_manager)
        self.assertEqual(JournalCompanyContract.objects.count(), 2)

    def test_contract_qs_journal_manager_sees_own_journal_contracts(self):
        """JOURNAL_TEAM_ADMIN sees contracts for their managed journals."""
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=self.journal_manager, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        self.assertFalse(is_collection_manager)
        managed_journal_ids = JournalTeamMember.objects.filter(
            user=self.journal_manager, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("journal", flat=True)
        filtered = JournalCompanyContract.objects.filter(journal__in=managed_journal_ids)
        self.assertEqual(filtered.count(), 1)
        self.assertEqual(filtered.first(), self.contract)

    def test_contract_qs_non_manager_sees_none(self):
        """Users with no manager role see no contracts."""
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=self.journal_member, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        self.assertFalse(is_collection_manager)
        managed_journal_ids = JournalTeamMember.objects.filter(
            user=self.journal_member, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("journal", flat=True)
        filtered = JournalCompanyContract.objects.filter(journal__in=managed_journal_ids)
        self.assertEqual(filtered.count(), 0)
