from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

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
    TeamRole,
)
from upload.models import Package, PackageZip, choices

User = get_user_model()


def populate_package_scope(scope):
    CreateUserGroupsCommand().handle(stdout=StringIO(), sync_users=False)
    scope.factory = RequestFactory()

    scope.superuser = User.objects.create_superuser(
        username="admin", email="admin@example.com", password="password"
    )
    scope.analyst_user = User.objects.create_user(
        username="analyst", email="analyst@example.com", password="password"
    )
    scope.company_user = User.objects.create_user(
        username="provider",
        email="provider@example.com",
        password="password",
        is_staff=True,
    )
    scope.unrelated_user = User.objects.create_user(
        username="unrelated", email="unrelated@example.com", password="password"
    )

    scope.collection = Collection.objects.create(
        acron="scl", name="SciELO Brazil", creator=scope.superuser
    )
    CollectionTeamMember.objects.create(
        user=scope.analyst_user,
        collection=scope.collection,
        role=TeamRole.MEMBER,
        is_active_member=True,
        creator=scope.superuser,
    )

    scope.official_j1 = OfficialJournal.objects.create(
        title="Journal One", issn_electronic="1111-1111", creator=scope.superuser
    )
    scope.journal_1 = Journal.objects.create(
        official_journal=scope.official_j1,
        journal_acron="J1",
        creator=scope.superuser,
    )
    JournalCollection.objects.create(
        journal=scope.journal_1, collection=scope.collection, creator=scope.superuser
    )

    scope.official_j2 = OfficialJournal.objects.create(
        title="Journal Two", issn_electronic="2222-2222", creator=scope.superuser
    )
    scope.journal_2 = Journal.objects.create(
        official_journal=scope.official_j2,
        journal_acron="J2",
        creator=scope.superuser,
    )

    scope.company = Company.objects.create(name="Alpha XML", creator=scope.superuser)
    CompanyTeamMember.objects.create(
        user=scope.company_user,
        company=scope.company,
        role=TeamRole.MEMBER,
        is_active_member=True,
        creator=scope.superuser,
    )
    JournalCompanyContract.objects.create(
        journal=scope.journal_1,
        company=scope.company,
        is_active=True,
        creator=scope.superuser,
    )

    fake_file = SimpleUploadedFile("sample.zip", b"PK\x05\x06" + b"\x00" * 18)
    scope.pkg_zip_1 = PackageZip.objects.create(
        name="pkg1",
        file=fake_file,
        creator=scope.company_user,
    )

    scope.package_1 = Package.objects.create(
        pkg_zip=scope.pkg_zip_1,
        journal=scope.journal_1,
        status=choices.PS_VALIDATED_WITH_ERRORS,
        creator=scope.company_user,
        file=fake_file,
    )

    scope.package_2 = Package.objects.create(
        journal=scope.journal_2,
        status=choices.PS_VALIDATED_WITH_ERRORS,
        creator=scope.unrelated_user,
        file=fake_file,
    )
