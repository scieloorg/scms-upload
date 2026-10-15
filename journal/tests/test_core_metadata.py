from datetime import timedelta
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from journal.models import Journal, OfficialJournal


class JournalCoreMetadataTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="journal-review")

    def test_official_journal_lookup_prefers_exact_match_then_latest_issn_match(self):
        expected = OfficialJournal.objects.create(
            creator=self.user,
            issn_electronic="1111-1111",
            issn_print="2222-2222",
            issnl="4444-4444",
        )
        other = OfficialJournal.objects.create(
            creator=self.user, issn_electronic="1111-1111", issn_print="3333-3333"
        )
        OfficialJournal.objects.filter(pk=expected.pk).update(
            updated=timezone.now() - timedelta(days=1)
        )

        for query, match in (
            ({"issn_electronic": "1111-1111", "issn_print": "2222-2222"}, expected),
            ({"issn_electronic": "1111-1111"}, other),
            ({"issn_electronic": "2222-2222"}, expected),
            ({"issnl": "2222-2222"}, expected),
            ({"issnl": "4444-4444"}, expected),
        ):
            with self.subTest(query=query):
                self.assertEqual(OfficialJournal.get(**query), match)

        with self.assertRaises(OfficialJournal.DoesNotExist):
            OfficialJournal.get(issn_electronic="9999-9999")

    def test_journal_update_preserves_acronym_when_omitted(self):
        official = OfficialJournal.objects.create(
            creator=self.user, issn_print="2222-2222"
        )
        journal = Journal.objects.create(
            creator=self.user, official_journal=official, journal_acron="rbt"
        )

        updated = Journal.create_or_update(self.user, official_journal=official)

        self.assertEqual(updated.pk, journal.pk)
        self.assertEqual(updated.journal_acron, "rbt")

    def test_completeness_accepts_one_issn_and_owner_or_publisher(self):
        for field in ("issn_print", "issn_electronic"):
            with self.subTest(field=field):
                official = OfficialJournal.objects.create(
                    creator=self.user, **{field: "1111-1111"}
                )
                journal = Journal.objects.create(
                    creator=self.user, official_journal=official
                )
                self.assertNotIn(_("Electronic ISSN"), journal.missing_fields)
                self.assertNotIn(_("Print ISSN"), journal.missing_fields)

        for owner, publisher in ((True, False), (False, True), (False, False)):
            with self.subTest(owner=owner, publisher=publisher):
                journal = MagicMock()
                journal.official_journal = None
                journal.owner.exists.return_value = owner
                journal.publisher.exists.return_value = publisher
                journal.collections = []
                missing = Journal.missing_fields.fget(journal)
                self.assertEqual(_("owner") in missing, not (owner or publisher))
                self.assertEqual(_("publisher") in missing, not (owner or publisher))
