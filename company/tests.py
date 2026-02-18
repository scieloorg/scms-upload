import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from company.models import Company, CompanyMember
from core.users.tests.factories import UserFactory

User = get_user_model()


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def another_user():
    return UserFactory()


@pytest.fixture
def company(user):
    return Company.objects.create(
        name="Test Company",
        acronym="TC",
        creator=user,
    )


@pytest.fixture
def company_with_manager(user, company):
    CompanyMember.objects.create(
        company=company,
        user=user,
        role=CompanyMember.MANAGER,
        creator=user,
    )
    return company


@pytest.mark.django_db
class TestCompanyModel:
    def test_create_company(self, user):
        """Test creating a company."""
        company = Company.objects.create(
            name="XML Providers Inc",
            acronym="XPI",
            description="A company that provides XML services",
            creator=user,
        )
        
        assert company.name == "XML Providers Inc"
        assert company.acronym == "XPI"
        assert str(company) == "XML Providers Inc"

    def test_company_unique_name(self, user, company):
        """Test that company names must be unique."""
        with pytest.raises(IntegrityError):
            Company.objects.create(
                name="Test Company",
                creator=user,
            )

    def test_company_managers_property(self, user, another_user, company):
        """Test the managers property returns only managers."""
        # Add a manager
        CompanyMember.objects.create(
            company=company,
            user=user,
            role=CompanyMember.MANAGER,
            creator=user,
        )
        
        # Add a regular member
        CompanyMember.objects.create(
            company=company,
            user=another_user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        managers = company.managers
        assert managers.count() == 1
        assert managers.first().user == user

    def test_company_has_manager(self, user, company_with_manager):
        """Test has_manager method."""
        assert company_with_manager.has_manager(user) is True

    def test_company_has_member(self, user, another_user, company_with_manager):
        """Test has_member method."""
        # Manager is also a member
        assert company_with_manager.has_member(user) is True
        
        # Regular member
        CompanyMember.objects.create(
            company=company_with_manager,
            user=another_user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        assert company_with_manager.has_member(another_user) is True


@pytest.mark.django_db
class TestCompanyMemberModel:
    def test_create_company_member(self, user, company):
        """Test creating a company member."""
        member = CompanyMember.objects.create(
            company=company,
            user=user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        assert member.company == company
        assert member.user == user
        assert member.role == CompanyMember.MEMBER
        assert member.is_active_member is True

    def test_create_company_manager(self, user, company):
        """Test creating a company manager."""
        manager = CompanyMember.objects.create(
            company=company,
            user=user,
            role=CompanyMember.MANAGER,
            creator=user,
        )
        
        assert manager.role == CompanyMember.MANAGER
        assert str(manager) == f"{user} (Manager) - {company}"

    def test_unique_user_company_constraint(self, user, company):
        """Test that a user can only be a member of a company once."""
        CompanyMember.objects.create(
            company=company,
            user=user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        with pytest.raises(IntegrityError):
            CompanyMember.objects.create(
                company=company,
                user=user,
                role=CompanyMember.MANAGER,
                creator=user,
            )

    def test_cannot_remove_last_manager(self, user, company_with_manager):
        """Test that the last manager cannot be removed."""
        member = CompanyMember.objects.get(company=company_with_manager, user=user)
        
        with pytest.raises(ValidationError):
            member.delete()

    def test_cannot_demote_last_manager(self, user, company_with_manager):
        """Test that the last manager cannot be demoted to member."""
        member = CompanyMember.objects.get(company=company_with_manager, user=user)
        member.role = CompanyMember.MEMBER
        
        with pytest.raises(ValidationError):
            member.save()

    def test_cannot_deactivate_last_manager(self, user, company_with_manager):
        """Test that the last manager cannot be deactivated."""
        member = CompanyMember.objects.get(company=company_with_manager, user=user)
        member.is_active_member = False
        
        with pytest.raises(ValidationError):
            member.save()

    def test_can_remove_manager_when_multiple_exist(self, user, another_user, company_with_manager):
        """Test that a manager can be removed when multiple managers exist."""
        # Add second manager
        CompanyMember.objects.create(
            company=company_with_manager,
            user=another_user,
            role=CompanyMember.MANAGER,
            creator=user,
        )
        
        # Now we can remove the first manager
        member = CompanyMember.objects.get(company=company_with_manager, user=user)
        member.delete()
        
        assert CompanyMember.objects.filter(
            company=company_with_manager,
            role=CompanyMember.MANAGER,
        ).count() == 1

    def test_can_demote_manager_when_multiple_exist(self, user, another_user, company_with_manager):
        """Test that a manager can be demoted when multiple managers exist."""
        # Add second manager
        CompanyMember.objects.create(
            company=company_with_manager,
            user=another_user,
            role=CompanyMember.MANAGER,
            creator=user,
        )
        
        # Now we can demote the first manager
        member = CompanyMember.objects.get(company=company_with_manager, user=user)
        member.role = CompanyMember.MEMBER
        member.save()
        
        assert member.role == CompanyMember.MEMBER

    def test_can_remove_regular_member(self, user, another_user, company_with_manager):
        """Test that a regular member can be removed."""
        member = CompanyMember.objects.create(
            company=company_with_manager,
            user=another_user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        # Should not raise any exception
        member.delete()
        
        assert not CompanyMember.objects.filter(pk=member.pk).exists()

    def test_user_can_be_member_of_multiple_companies(self, user):
        """Test that a user can be a member of multiple companies."""
        company1 = Company.objects.create(name="Company 1", creator=user)
        company2 = Company.objects.create(name="Company 2", creator=user)
        
        CompanyMember.objects.create(
            company=company1,
            user=user,
            role=CompanyMember.MANAGER,
            creator=user,
        )
        
        CompanyMember.objects.create(
            company=company2,
            user=user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        assert user.company_memberships.count() == 2


@pytest.mark.django_db
class TestCompanyPermissions:
    def test_manager_can_edit_company(self, user, company_with_manager):
        """Test that a manager can edit their company."""
        from company.permission_helper import CompanyPermissionHelper
        
        helper = CompanyPermissionHelper(Company)
        assert helper.user_can_edit_obj(user, company_with_manager) is True

    def test_member_cannot_edit_company(self, user, another_user, company_with_manager):
        """Test that a regular member cannot edit the company."""
        from company.permission_helper import CompanyPermissionHelper
        
        # Add another_user as regular member
        CompanyMember.objects.create(
            company=company_with_manager,
            user=another_user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        helper = CompanyPermissionHelper(Company)
        assert helper.user_can_edit_obj(another_user, company_with_manager) is False

    def test_non_member_cannot_edit_company(self, another_user, company_with_manager):
        """Test that a non-member cannot edit the company."""
        from company.permission_helper import CompanyPermissionHelper
        
        helper = CompanyPermissionHelper(Company)
        assert helper.user_can_edit_obj(another_user, company_with_manager) is False

    def test_manager_can_add_members(self, user, company_with_manager):
        """Test that a manager can add new members."""
        from company.permission_helper import CompanyMemberPermissionHelper
        
        helper = CompanyMemberPermissionHelper(CompanyMember)
        assert helper.user_can_create(user) is True

    def test_member_cannot_add_members(self, user, another_user, company_with_manager):
        """Test that a regular member cannot add new members."""
        from company.permission_helper import CompanyMemberPermissionHelper
        
        # Add another_user as regular member
        CompanyMember.objects.create(
            company=company_with_manager,
            user=another_user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        helper = CompanyMemberPermissionHelper(CompanyMember)
        assert helper.user_can_create(another_user) is False

    def test_manager_can_edit_own_company_members(self, user, another_user, company_with_manager):
        """Test that a manager can edit members of their own company."""
        from company.permission_helper import CompanyMemberPermissionHelper
        
        member = CompanyMember.objects.create(
            company=company_with_manager,
            user=another_user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        helper = CompanyMemberPermissionHelper(CompanyMember)
        assert helper.user_can_edit_obj(user, member) is True

    def test_manager_cannot_edit_other_company_members(self, user, another_user):
        """Test that a manager cannot edit members of another company."""
        from company.permission_helper import CompanyMemberPermissionHelper
        
        # Create two companies
        company1 = Company.objects.create(name="Company 1", creator=user)
        company2 = Company.objects.create(name="Company 2", creator=user)
        
        # User is manager of company1
        CompanyMember.objects.create(
            company=company1,
            user=user,
            role=CompanyMember.MANAGER,
            creator=user,
        )
        
        # Another user is member of company2
        member2 = CompanyMember.objects.create(
            company=company2,
            user=another_user,
            role=CompanyMember.MEMBER,
            creator=user,
        )
        
        helper = CompanyMemberPermissionHelper(CompanyMember)
        assert helper.user_can_edit_obj(user, member2) is False
