from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from journal.models import Journal, OfficialJournal
from team.models import (
    CollectionTeamMember,
    Company,
    CompanyTeamMember,
    JournalCompanyContract,
    JournalTeamMember,
    TeamRole,
)
from team.policies import (
    CollectionTeamMemberPolicy,
    CompanyPolicy,
    JournalCompanyContractPolicy,
    JournalTeamMemberPolicy,
)

User = get_user_model()


class JournalCompanyContractPolicyTest(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="pass"
        )
        self.collection = Collection.objects.create(
            acron="scl", name="SciELO Brazil", creator=self.creator
        )

        self.official_journal_a = OfficialJournal.objects.create(
            title="Journal A",
            issn_electronic="1111-1111",
            creator=self.creator,
        )
        self.journal_a = Journal.objects.create(
            official_journal=self.official_journal_a,
            journal_acron="ja",
            creator=self.creator,
        )

        self.official_journal_b = OfficialJournal.objects.create(
            title="Journal B",
            issn_electronic="2222-2222",
            creator=self.creator,
        )
        self.journal_b = Journal.objects.create(
            official_journal=self.official_journal_b,
            journal_acron="jb",
            creator=self.creator,
        )

        self.company_a = Company.objects.create(
            name="Company Alpha",
            creator=self.creator,
        )
        self.company_b = Company.objects.create(
            name="Company Beta",
            creator=self.creator,
        )

        self.contract_a1 = JournalCompanyContract.objects.create(
            journal=self.journal_a,
            company=self.company_a,
            is_active=True,
            creator=self.creator,
        )
        self.contract_a2 = JournalCompanyContract.objects.create(
            journal=self.journal_a,
            company=self.company_b,
            is_active=False,
            creator=self.creator,
        )
        self.contract_b1 = JournalCompanyContract.objects.create(
            journal=self.journal_b,
            company=self.company_a,
            is_active=True,
            creator=self.creator,
        )
        self.contract_b2 = JournalCompanyContract.objects.create(
            journal=self.journal_b,
            company=self.company_b,
            is_active=False,
            creator=self.creator,
        )

        self.col_admin = User.objects.create_user(
            username="col_admin", email="col_admin@example.com", password="pass"
        )
        CollectionTeamMember.objects.create(
            user=self.col_admin,
            collection=self.collection,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.creator,
        )

        self.journal_admin = User.objects.create_user(
            username="j_admin", email="j_admin@example.com", password="pass"
        )
        JournalTeamMember.objects.create(
            user=self.journal_admin,
            journal=self.journal_a,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.creator,
        )

        self.journal_member = User.objects.create_user(
            username="j_member", email="j_member@example.com", password="pass"
        )
        JournalTeamMember.objects.create(
            user=self.journal_member,
            journal=self.journal_a,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.creator,
        )

        self.company_admin = User.objects.create_user(
            username="c_admin", email="c_admin@example.com", password="pass"
        )
        CompanyTeamMember.objects.create(
            user=self.company_admin,
            company=self.company_a,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.creator,
        )

        self.company_member = User.objects.create_user(
            username="c_member", email="c_member@example.com", password="pass"
        )
        CompanyTeamMember.objects.create(
            user=self.company_member,
            company=self.company_a,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.creator,
        )

        self.outsider = User.objects.create_user(
            username="outsider", email="outsider@example.com", password="pass"
        )

    def test_collection_admin_does_not_manage_contracts(self):
        qs = JournalCompanyContractPolicy.scope_queryset(
            self.col_admin, JournalCompanyContract.objects.all()
        )
        self.assertEqual(qs.count(), 0)

    def test_journal_admin_sees_active_and_inactive_contracts_for_managed_journal_only(
        self,
    ):
        qs = JournalCompanyContractPolicy.scope_queryset(
            self.journal_admin, JournalCompanyContract.objects.all()
        )
        self.assertCountEqual(
            list(qs.values_list("id", flat=True)),
            [self.contract_a1.id, self.contract_a2.id],
        )

    def test_journal_member_sees_only_active_contracts_for_member_journal(self):
        qs = JournalCompanyContractPolicy.scope_queryset(
            self.journal_member, JournalCompanyContract.objects.all()
        )
        self.assertCountEqual(
            list(qs.values_list("id", flat=True)),
            [self.contract_a1.id],
        )

    def test_company_admin_and_member_see_only_active_contracts_for_company(self):
        qs_admin = JournalCompanyContractPolicy.scope_queryset(
            self.company_admin, JournalCompanyContract.objects.all()
        )
        self.assertCountEqual(
            list(qs_admin.values_list("id", flat=True)),
            [self.contract_a1.id, self.contract_b1.id],
        )

        qs_member = JournalCompanyContractPolicy.scope_queryset(
            self.company_member, JournalCompanyContract.objects.all()
        )
        self.assertCountEqual(
            list(qs_member.values_list("id", flat=True)),
            [self.contract_a1.id, self.contract_b1.id],
        )

    def test_outsider_sees_no_contracts(self):
        qs = JournalCompanyContractPolicy.scope_queryset(
            self.outsider, JournalCompanyContract.objects.all()
        )
        self.assertEqual(qs.count(), 0)


class JournalTeamMemberPolicyTest(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator2", email="creator2@example.com", password="pass"
        )
        self.collection = Collection.objects.create(
            acron="scl", name="SciELO Brazil", creator=self.creator
        )

        self.official_journal_a = OfficialJournal.objects.create(
            title="Journal A",
            issn_electronic="1111-1111",
            creator=self.creator,
        )
        self.journal_a = Journal.objects.create(
            official_journal=self.official_journal_a,
            journal_acron="ja",
            creator=self.creator,
        )

        self.official_journal_b = OfficialJournal.objects.create(
            title="Journal B",
            issn_electronic="2222-2222",
            creator=self.creator,
        )
        self.journal_b = Journal.objects.create(
            official_journal=self.official_journal_b,
            journal_acron="jb",
            creator=self.creator,
        )

        self.col_admin = User.objects.create_user(
            username="col_admin2", email="col_admin2@example.com", password="pass"
        )
        CollectionTeamMember.objects.create(
            user=self.col_admin,
            collection=self.collection,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.creator,
        )

        self.j_admin_a = User.objects.create_user(
            username="j_admin_a", email="j_admin_a@example.com", password="pass"
        )
        self.member_admin_a = JournalTeamMember.objects.create(
            user=self.j_admin_a,
            journal=self.journal_a,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.creator,
        )

        self.j_member_a = User.objects.create_user(
            username="j_member_a", email="j_member_a@example.com", password="pass"
        )
        self.member_team_a = JournalTeamMember.objects.create(
            user=self.j_member_a,
            journal=self.journal_a,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.creator,
        )

        self.j_admin_b = User.objects.create_user(
            username="j_admin_b", email="j_admin_b@example.com", password="pass"
        )
        self.member_admin_b = JournalTeamMember.objects.create(
            user=self.j_admin_b,
            journal=self.journal_b,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.creator,
        )

        self.outsider = User.objects.create_user(
            username="outsider2", email="outsider2@example.com", password="pass"
        )

    def test_collection_admin_does_not_manage_journal_team_members(self):
        qs = JournalTeamMemberPolicy.scope_queryset(
            self.col_admin, JournalTeamMember.objects.all()
        )
        self.assertEqual(qs.count(), 0)

    def test_journal_admin_sees_only_members_of_managed_journal(self):
        qs = JournalTeamMemberPolicy.scope_queryset(
            self.j_admin_a, JournalTeamMember.objects.all()
        )
        self.assertCountEqual(
            list(qs.values_list("id", flat=True)),
            [self.member_admin_a.id, self.member_team_a.id],
        )

    def test_journal_member_sees_only_self(self):
        qs = JournalTeamMemberPolicy.scope_queryset(
            self.j_member_a, JournalTeamMember.objects.all()
        )
        self.assertCountEqual(
            list(qs.values_list("id", flat=True)),
            [self.member_team_a.id],
        )

    def test_outsider_sees_no_journal_team_members(self):
        qs = JournalTeamMemberPolicy.scope_queryset(
            self.outsider, JournalTeamMember.objects.all()
        )
        self.assertEqual(qs.count(), 0)


class CollectionTeamMemberPolicyTest(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator3", email="creator3@example.com", password="pass"
        )
        self.collection_a = Collection.objects.create(
            acron="scl", name="SciELO Brazil", creator=self.creator
        )
        self.collection_b = Collection.objects.create(
            acron="spa", name="SciELO Public Health", creator=self.creator
        )

        self.col_admin = User.objects.create_user(
            username="col_admin3", email="col_admin3@example.com", password="pass"
        )
        self.member_admin = CollectionTeamMember.objects.create(
            user=self.col_admin,
            collection=self.collection_a,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.creator,
        )

        self.col_member = User.objects.create_user(
            username="col_member3", email="col_member3@example.com", password="pass"
        )
        self.member_regular = CollectionTeamMember.objects.create(
            user=self.col_member,
            collection=self.collection_b,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.creator,
        )

        self.outsider = User.objects.create_user(
            username="outsider3", email="outsider3@example.com", password="pass"
        )

    def test_collection_admin_sees_only_managed_collection_team_members(self):
        qs = CollectionTeamMemberPolicy.scope_queryset(
            self.col_admin, CollectionTeamMember.objects.all()
        )
        self.assertCountEqual(
            list(qs.values_list("id", flat=True)),
            [self.member_admin.id],
        )

    def test_collection_member_sees_only_self(self):
        qs = CollectionTeamMemberPolicy.scope_queryset(
            self.col_member, CollectionTeamMember.objects.all()
        )
        self.assertCountEqual(
            list(qs.values_list("id", flat=True)),
            [self.member_regular.id],
        )

    def test_outsider_sees_no_collection_team_members(self):
        qs = CollectionTeamMemberPolicy.scope_queryset(
            self.outsider, CollectionTeamMember.objects.all()
        )
        self.assertEqual(qs.count(), 0)


class CompanyPolicyTest(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator4", email="creator4@example.com", password="pass"
        )
        self.collection = Collection.objects.create(
            acron="scl", name="SciELO Brazil", creator=self.creator
        )

        self.company_a = Company.objects.create(
            name="Company Alpha",
            creator=self.creator,
        )
        self.company_b = Company.objects.create(
            name="Company Beta",
            creator=self.creator,
        )

        self.col_admin = User.objects.create_user(
            username="col_admin4", email="col_admin4@example.com", password="pass"
        )
        CollectionTeamMember.objects.create(
            user=self.col_admin,
            collection=self.collection,
            role=TeamRole.MANAGER,
            is_active_member=True,
            creator=self.creator,
        )

        self.comp_user = User.objects.create_user(
            username="comp_user", email="comp_user@example.com", password="pass"
        )
        CompanyTeamMember.objects.create(
            user=self.comp_user,
            company=self.company_a,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=self.creator,
        )

        self.outsider = User.objects.create_user(
            username="outsider4", email="outsider4@example.com", password="pass"
        )

    def test_collection_admin_sees_all_companies(self):
        qs = CompanyPolicy.scope_queryset(self.col_admin, Company.objects.all())
        self.assertEqual(qs.count(), 2)

    def test_company_member_sees_only_own_company(self):
        qs = CompanyPolicy.scope_queryset(self.comp_user, Company.objects.all())
        self.assertCountEqual(
            list(qs.values_list("id", flat=True)),
            [self.company_a.id],
        )

    def test_outsider_sees_no_companies(self):
        qs = CompanyPolicy.scope_queryset(self.outsider, Company.objects.all())
        self.assertEqual(qs.count(), 0)
