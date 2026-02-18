from django.test import TestCase

# Create your tests here.


import pytest
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from company.models import Company, CompanyMember
from journal.models import Journal, JournalMember, JournalCompanyContract
from core.users.tests.factories import UserFactory

User = get_user_model()


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def another_user():
    return UserFactory()


@pytest.fixture
def journal(user):
    return Journal.objects.create(
        title="Test Journal",
        journal_acron="TJ",
        creator=user,
    )


@pytest.fixture
def journal_with_manager(user, journal):
    JournalMember.objects.create(
        journal=journal,
        user=user,
        role=JournalMember.MANAGER,
        creator=user,
    )
    return journal


@pytest.fixture
def company(user):
    return Company.objects.create(
        name="Test Company",
        acronym="TC",
        creator=user,
    )


@pytest.mark.django_db
class TestJournalMemberModel:
    def test_create_journal_member(self, user, journal):
        """Test creating a journal member."""
        member = JournalMember.objects.create(
            journal=journal,
            user=user,
            role=JournalMember.MEMBER,
            creator=user,
        )
        
        assert member.journal == journal
        assert member.user == user
        assert member.role == JournalMember.MEMBER
        assert member.is_active_member is True

    def test_create_journal_manager(self, user, journal):
        """Test creating a journal manager."""
        manager = JournalMember.objects.create(
            journal=journal,
            user=user,
            role=JournalMember.MANAGER,
            creator=user,
        )
        
        assert manager.role == JournalMember.MANAGER
        assert str(manager) == f"{user} (Manager) - {journal}"

    def test_unique_user_journal_constraint(self, user, journal):
        """Test that a user can only be a member of a journal once."""
        JournalMember.objects.create(
            journal=journal,
            user=user,
            role=JournalMember.MEMBER,
            creator=user,
        )
        
        with pytest.raises(IntegrityError):
            JournalMember.objects.create(
                journal=journal,
                user=user,
                role=JournalMember.MANAGER,
                creator=user,
            )

    def test_cannot_remove_last_manager(self, user, journal_with_manager):
        """Test that the last manager cannot be removed."""
        member = JournalMember.objects.get(journal=journal_with_manager, user=user)
        
        with pytest.raises(ValidationError):
            member.delete()

    def test_cannot_demote_last_manager(self, user, journal_with_manager):
        """Test that the last manager cannot be demoted to member."""
        member = JournalMember.objects.get(journal=journal_with_manager, user=user)
        member.role = JournalMember.MEMBER
        
        with pytest.raises(ValidationError):
            member.save()

    def test_cannot_deactivate_last_manager(self, user, journal_with_manager):
        """Test that the last manager cannot be deactivated."""
        member = JournalMember.objects.get(journal=journal_with_manager, user=user)
        member.is_active_member = False
        
        with pytest.raises(ValidationError):
            member.save()

    def test_can_remove_manager_when_multiple_exist(self, user, another_user, journal_with_manager):
        """Test that a manager can be removed when multiple managers exist."""
        # Add second manager
        JournalMember.objects.create(
            journal=journal_with_manager,
            user=another_user,
            role=JournalMember.MANAGER,
            creator=user,
        )
        
        # Now we can remove the first manager
        member = JournalMember.objects.get(journal=journal_with_manager, user=user)
        member.delete()
        
        assert JournalMember.objects.filter(
            journal=journal_with_manager,
            role=JournalMember.MANAGER,
        ).count() == 1

    def test_can_demote_manager_when_multiple_exist(self, user, another_user, journal_with_manager):
        """Test that a manager can be demoted when multiple managers exist."""
        # Add second manager
        JournalMember.objects.create(
            journal=journal_with_manager,
            user=another_user,
            role=JournalMember.MANAGER,
            creator=user,
        )
        
        # Now we can demote the first manager
        member = JournalMember.objects.get(journal=journal_with_manager, user=user)
        member.role = JournalMember.MEMBER
        member.save()
        
        assert member.role == JournalMember.MEMBER

    def test_can_remove_regular_member(self, user, another_user, journal_with_manager):
        """Test that a regular member can be removed."""
        member = JournalMember.objects.create(
            journal=journal_with_manager,
            user=another_user,
            role=JournalMember.MEMBER,
            creator=user,
        )
        
        # Should not raise any exception
        member.delete()
        
        assert not JournalMember.objects.filter(pk=member.pk).exists()

    def test_user_can_be_member_of_multiple_journals(self, user):
        """Test that a user can be a member of multiple journals."""
        journal1 = Journal.objects.create(
            title="Journal 1",
            journal_acron="J1",
            creator=user,
        )
        journal2 = Journal.objects.create(
            title="Journal 2",
            journal_acron="J2",
            creator=user,
        )
        
        JournalMember.objects.create(
            journal=journal1,
            user=user,
            role=JournalMember.MANAGER,
            creator=user,
        )
        
        JournalMember.objects.create(
            journal=journal2,
            user=user,
            role=JournalMember.MEMBER,
            creator=user,
        )
        
        assert user.journal_memberships.count() == 2


@pytest.mark.django_db
class TestJournalCompanyContractModel:
    def test_create_contract(self, user, journal, company):
        """Test creating a journal-company contract."""
        contract = JournalCompanyContract.objects.create(
            journal=journal,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        assert contract.journal == journal
        assert contract.company == company
        assert contract.is_active is True
        assert str(contract) == f"{journal} - {company} (Active)"

    def test_contract_is_active_property(self, user, journal, company):
        """Test that contract is_active property works correctly."""
        # Active contract (no end date)
        active_contract = JournalCompanyContract.objects.create(
            journal=journal,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        assert active_contract.is_active is True
        
        # Create another journal for ended contract
        journal2 = Journal.objects.create(
            title="Journal 2",
            journal_acron="J2",
            creator=user,
        )
        
        # Ended contract (has end date)
        ended_contract = JournalCompanyContract.objects.create(
            journal=journal2,
            company=company,
            initial_date=date.today() - timedelta(days=365),
            final_date=date.today() - timedelta(days=1),
            creator=user,
        )
        assert ended_contract.is_active is False

    def test_end_contract(self, user, journal, company):
        """Test ending a contract."""
        contract = JournalCompanyContract.objects.create(
            journal=journal,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        assert contract.is_active is True
        
        end_date = date.today()
        contract.end_contract(end_date)
        
        assert contract.is_active is False
        assert contract.final_date == end_date

    def test_end_contract_without_date(self, user, journal, company):
        """Test ending a contract without specifying date (uses today)."""
        contract = JournalCompanyContract.objects.create(
            journal=journal,
            company=company,
            initial_date=date.today() - timedelta(days=30),
            creator=user,
        )
        
        contract.end_contract()
        
        assert contract.is_active is False
        assert contract.final_date == date.today()

    def test_unique_journal_company_constraint(self, user, journal, company):
        """Test that a journal can only have one contract with a company."""
        JournalCompanyContract.objects.create(
            journal=journal,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        with pytest.raises(IntegrityError):
            JournalCompanyContract.objects.create(
                journal=journal,
                company=company,
                initial_date=date.today(),
                creator=user,
            )

    def test_journal_can_have_multiple_companies(self, user, journal):
        """Test that a journal can have contracts with multiple companies."""
        company1 = Company.objects.create(name="Company 1", creator=user)
        company2 = Company.objects.create(name="Company 2", creator=user)
        
        JournalCompanyContract.objects.create(
            journal=journal,
            company=company1,
            initial_date=date.today(),
            creator=user,
        )
        
        JournalCompanyContract.objects.create(
            journal=journal,
            company=company2,
            initial_date=date.today(),
            creator=user,
        )
        
        assert journal.company_contracts.count() == 2

    def test_company_can_have_multiple_journals(self, user, company):
        """Test that a company can have contracts with multiple journals."""
        journal1 = Journal.objects.create(
            title="Journal 1",
            journal_acron="J1",
            creator=user,
        )
        journal2 = Journal.objects.create(
            title="Journal 2",
            journal_acron="J2",
            creator=user,
        )
        
        JournalCompanyContract.objects.create(
            journal=journal1,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        JournalCompanyContract.objects.create(
            journal=journal2,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        assert company.journal_contracts.count() == 2

    def test_contract_with_notes(self, user, journal, company):
        """Test creating a contract with notes."""
        notes = "This is a contract for XML production services."
        contract = JournalCompanyContract.objects.create(
            journal=journal,
            company=company,
            initial_date=date.today(),
            notes=notes,
            creator=user,
        )
        
        assert contract.notes == notes


@pytest.mark.django_db
class TestIntegrationScenarios:
    def test_company_member_can_work_with_contracted_journals(self, user, another_user):
        """Test that a company member can work with journals contracted by their company."""
        # Create company with two members
        company = Company.objects.create(name="XML Services Ltd", creator=user)
        CompanyMember.objects.create(
            company=company,
            user=user,
            role=CompanyMember.MANAGER,
            creator=user,
        )
        CompanyMember.objects.create(
            company=company,
            user=another_user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        # Create two journals
        journal1 = Journal.objects.create(
            title="Journal A",
            journal_acron="JA",
            creator=user,
        )
        journal2 = Journal.objects.create(
            title="Journal B",
            journal_acron="JB",
            creator=user,
        )
        
        # Company has contracts with both journals
        JournalCompanyContract.objects.create(
            journal=journal1,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        JournalCompanyContract.objects.create(
            journal=journal2,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        # Verify the member can access contracted journals
        member_companies = CompanyMember.objects.filter(user=another_user)
        contracted_journals = JournalCompanyContract.objects.filter(
            company__in=[m.company for m in member_companies],
            final_date__isnull=True,  # Only active contracts
        )
        
        assert contracted_journals.count() == 2
        assert journal1 in [c.journal for c in contracted_journals]
        assert journal2 in [c.journal for c in contracted_journals]

    def test_journal_manager_can_manage_contracts(self, user, another_user):
        """Test that journal managers can manage contracts."""
        # Create journal with manager
        journal = Journal.objects.create(
            title="Science Journal",
            journal_acron="SJ",
            creator=user,
        )
        JournalMember.objects.create(
            journal=journal,
            user=user,
            role=JournalMember.MANAGER,
            creator=user,
        )
        
        # Create company
        company = Company.objects.create(name="Production Co", creator=user)
        
        # Manager creates a contract
        contract = JournalCompanyContract.objects.create(
            journal=journal,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        assert contract.is_active is True
        
        # Manager ends the contract
        contract.end_contract()
        
        assert contract.is_active is False


@pytest.mark.django_db
class TestJournalMemberPermissions:
    def test_manager_can_add_members(self, user, journal_with_manager):
        """Test that a journal manager can add new members."""
        from journal.permission_helper import JournalMemberPermissionHelper
        
        helper = JournalMemberPermissionHelper(JournalMember)
        assert helper.user_can_create(user) is True

    def test_member_cannot_add_members(self, user, another_user, journal_with_manager):
        """Test that a regular member cannot add new members."""
        from journal.permission_helper import JournalMemberPermissionHelper
        
        # Add another_user as regular member
        JournalMember.objects.create(
            journal=journal_with_manager,
            user=another_user,
            role=JournalMember.MEMBER,
            creator=user,
        )
        
        helper = JournalMemberPermissionHelper(JournalMember)
        assert helper.user_can_create(another_user) is False

    def test_manager_can_edit_own_journal_members(self, user, another_user, journal_with_manager):
        """Test that a manager can edit members of their own journal."""
        from journal.permission_helper import JournalMemberPermissionHelper
        
        member = JournalMember.objects.create(
            journal=journal_with_manager,
            user=another_user,
            role=JournalMember.MEMBER,
            creator=user,
        )
        
        helper = JournalMemberPermissionHelper(JournalMember)
        assert helper.user_can_edit_obj(user, member) is True

    def test_manager_cannot_edit_other_journal_members(self, user, another_user):
        """Test that a manager cannot edit members of another journal."""
        from journal.permission_helper import JournalMemberPermissionHelper
        
        # Create two journals
        journal1 = Journal.objects.create(
            title="Journal 1",
            journal_acron="J1",
            creator=user,
        )
        journal2 = Journal.objects.create(
            title="Journal 2",
            journal_acron="J2",
            creator=user,
        )
        
        # User is manager of journal1
        JournalMember.objects.create(
            journal=journal1,
            user=user,
            role=JournalMember.MANAGER,
            creator=user,
        )
        
        # Another user is member of journal2
        member2 = JournalMember.objects.create(
            journal=journal2,
            user=another_user,
            role=JournalMember.MEMBER,
            creator=user,
        )
        
        helper = JournalMemberPermissionHelper(JournalMember)
        assert helper.user_can_edit_obj(user, member2) is False


@pytest.mark.django_db
class TestJournalCompanyContractPermissions:
    def test_journal_manager_can_create_contracts(self, user, journal_with_manager):
        """Test that a journal manager can create contracts."""
        from journal.permission_helper import JournalCompanyContractPermissionHelper
        
        helper = JournalCompanyContractPermissionHelper(JournalCompanyContract)
        assert helper.user_can_create(user) is True

    def test_journal_member_cannot_create_contracts(self, user, another_user, journal_with_manager):
        """Test that a regular journal member cannot create contracts."""
        from journal.permission_helper import JournalCompanyContractPermissionHelper
        
        # Add another_user as regular member
        JournalMember.objects.create(
            journal=journal_with_manager,
            user=another_user,
            role=JournalMember.MEMBER,
            creator=user,
        )
        
        helper = JournalCompanyContractPermissionHelper(JournalCompanyContract)
        assert helper.user_can_create(another_user) is False

    def test_journal_manager_can_edit_own_contracts(self, user, journal_with_manager, company):
        """Test that a journal manager can edit contracts of their own journal."""
        from journal.permission_helper import JournalCompanyContractPermissionHelper
        
        contract = JournalCompanyContract.objects.create(
            journal=journal_with_manager,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        helper = JournalCompanyContractPermissionHelper(JournalCompanyContract)
        assert helper.user_can_edit_obj(user, contract) is True

    def test_journal_manager_cannot_edit_other_journal_contracts(self, user, another_user, company):
        """Test that a journal manager cannot edit contracts of another journal."""
        from journal.permission_helper import JournalCompanyContractPermissionHelper
        
        # Create two journals
        journal1 = Journal.objects.create(
            title="Journal 1",
            journal_acron="J1",
            creator=user,
        )
        journal2 = Journal.objects.create(
            title="Journal 2",
            journal_acron="J2",
            creator=user,
        )
        
        # User is manager of journal1
        JournalMember.objects.create(
            journal=journal1,
            user=user,
            role=JournalMember.MANAGER,
            creator=user,
        )
        
        # Contract is for journal2
        contract = JournalCompanyContract.objects.create(
            journal=journal2,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        helper = JournalCompanyContractPermissionHelper(JournalCompanyContract)
        assert helper.user_can_edit_obj(user, contract) is False

    def test_company_member_can_inspect_contracts(self, user, another_user, journal, company):
        """Test that a company member can inspect contracts involving their company."""
        from journal.permission_helper import JournalCompanyContractPermissionHelper
        
        # Create contract
        contract = JournalCompanyContract.objects.create(
            journal=journal,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        # Another user is member of the company
        CompanyMember.objects.create(
            company=company,
            user=another_user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        helper = JournalCompanyContractPermissionHelper(JournalCompanyContract)
        assert helper.user_can_inspect_obj(another_user, contract) is True

    def test_journal_member_can_inspect_contracts(self, user, another_user, journal_with_manager, company):
        """Test that a journal member can inspect contracts of their journal."""
        from journal.permission_helper import JournalCompanyContractPermissionHelper
        
        # Create contract
        contract = JournalCompanyContract.objects.create(
            journal=journal_with_manager,
            company=company,
            initial_date=date.today(),
            creator=user,
        )
        
        # Another user is member of the journal
        JournalMember.objects.create(
            journal=journal_with_manager,
            user=another_user,
            role=JournalMember.MEMBER,
            creator=user,
        )
        
        helper = JournalCompanyContractPermissionHelper(JournalCompanyContract)
        assert helper.user_can_inspect_obj(another_user, contract) is True
