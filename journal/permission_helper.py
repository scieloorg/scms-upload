from wagtail_modeladmin.helpers import PermissionHelper

from journal.models import JournalMember


class JournalMemberPermissionHelper(PermissionHelper):
    """
    Permission helper for JournalMember model.
    Only journal managers can manage team members.
    """

    def user_can_create(self, user):
        """
        User can add a member if they are a manager of at least one journal.
        """
        if user.is_superuser:
            return True
        return JournalMember.objects.filter(
            user=user,
            role=JournalMember.MANAGER,
            is_active_member=True,
        ).exists()

    def user_can_edit_obj(self, user, obj):
        """
        User can edit a member if they are a manager of the same journal.
        """
        if user.is_superuser:
            return True
        return JournalMember.objects.filter(
            journal=obj.journal,
            user=user,
            role=JournalMember.MANAGER,
            is_active_member=True,
        ).exists()

    def user_can_delete_obj(self, user, obj):
        """
        User can delete a member if they are a manager of the same journal.
        """
        if user.is_superuser:
            return True
        return JournalMember.objects.filter(
            journal=obj.journal,
            user=user,
            role=JournalMember.MANAGER,
            is_active_member=True,
        ).exists()

    def user_can_inspect_obj(self, user, obj):
        """
        User can inspect a member if they are a member of the same journal.
        """
        if user.is_superuser:
            return True
        return JournalMember.objects.filter(
            journal=obj.journal,
            user=user,
            is_active_member=True,
        ).exists()


class JournalCompanyContractPermissionHelper(PermissionHelper):
    """
    Permission helper for JournalCompanyContract model.
    Only journal managers can manage contracts.
    """

    def user_can_create(self, user):
        """
        User can create a contract if they are a manager of at least one journal.
        """
        if user.is_superuser:
            return True
        return JournalMember.objects.filter(
            user=user,
            role=JournalMember.MANAGER,
            is_active_member=True,
        ).exists()

    def user_can_edit_obj(self, user, obj):
        """
        User can edit a contract if they are a manager of the journal.
        """
        if user.is_superuser:
            return True
        return JournalMember.objects.filter(
            journal=obj.journal,
            user=user,
            role=JournalMember.MANAGER,
            is_active_member=True,
        ).exists()

    def user_can_delete_obj(self, user, obj):
        """
        User can delete a contract if they are a manager of the journal.
        """
        if user.is_superuser:
            return True
        return JournalMember.objects.filter(
            journal=obj.journal,
            user=user,
            role=JournalMember.MANAGER,
            is_active_member=True,
        ).exists()

    def user_can_inspect_obj(self, user, obj):
        """
        User can inspect a contract if they are:
        - A member of the journal, OR
        - A member of the company in the contract
        """
        if user.is_superuser:
            return True
        
        # Check if user is a member of the journal
        is_journal_member = JournalMember.objects.filter(
            journal=obj.journal,
            user=user,
            is_active_member=True,
        ).exists()
        
        if is_journal_member:
            return True
        
        # Check if user is a member of the company
        from company.models import CompanyMember
        is_company_member = CompanyMember.objects.filter(
            company=obj.company,
            user=user,
            is_active_member=True,
        ).exists()
        
        return is_company_member
