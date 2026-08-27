"""
Testes para issue/models.py.

Observação: assume-se que journal.models.Journal pode ser instanciado com
Journal.objects.create(creator=cls.user, journal_acron="jacron") sem argumentos obrigatórios (todos os campos
relevantes para os testes aqui usam null=True/blank=True nos modelos
observados). Caso o modelo real exija campos obrigatórios, ajuste
`setUpTestData` abaixo.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from issue.models import Issue, IssueUpdateError, TOC, TocSection
from journal.models import Journal

User = get_user_model()


class IssueGetTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="user1", password="pass")
        cls.journal = Journal.objects.create(creator=cls.user, journal_acron="jacron")

    def test_get_returns_existing_issue(self):
        issue = Issue.objects.create(
            journal=self.journal,
            volume="49",
            number="1",
            supplement=None,
            publication_year="2025",
            creator=self.user,
        )
        found = Issue.get(
            journal=self.journal, volume="49", supplement=None, number="1"
        )
        self.assertEqual(found.pk, issue.pk)

    def test_get_raises_does_not_exist(self):
        with self.assertRaises(Issue.DoesNotExist):
            Issue.get(
                journal=self.journal, volume="49", supplement=None, number="1"
            )

    def test_get_with_multiple_objects_returns_most_recently_updated(self):
        # unique_together não impede duplicidade quando os registros diferem
        # em campos fora do conjunto (ex: publication_year), então é possível
        # existirem duas linhas que colidem na busca por (journal, volume,
        # supplement, number).
        Issue.objects.create(
            journal=self.journal,
            volume="49",
            number="1",
            supplement=None,
            publication_year="2024",
            creator=self.user,
        )
        newest = Issue.objects.create(
            journal=self.journal,
            volume="49",
            number="1",
            supplement=None,
            publication_year="2025",
            creator=self.user,
        )
        newest.save()  # garante 'updated' mais recente

        found = Issue.get(
            journal=self.journal, volume="49", supplement=None, number="1"
        )
        self.assertEqual(found.pk, newest.pk)


class IssueUpdateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="user1", password="pass")
        cls.other_user = User.objects.create_user(username="user2", password="pass")
        cls.journal = Journal.objects.create(creator=cls.user, journal_acron="jacron")

    def test_update_sets_creator_on_first_save(self):
        issue = Issue()
        issue.update(
            self.user,
            self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
        )
        self.assertEqual(issue.creator, self.user)
        self.assertIsNone(issue.updated_by)
        self.assertIsNotNone(issue.pk)

    def test_update_sets_updated_by_when_creator_already_set(self):
        issue = Issue()
        issue.update(
            self.user,
            self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
        )
        issue.update(
            self.other_user,
            self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
        )
        self.assertEqual(issue.creator, self.user)
        self.assertEqual(issue.updated_by, self.other_user)

    def test_update_preserves_existing_order_and_pid_suffix(self):
        issue = Issue()
        issue.update(
            self.user,
            self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
            order=7,
            issue_pid_suffix="0007",
        )
        self.assertEqual(issue.order, 7)
        self.assertEqual(issue.issue_pid_suffix, "0007")

        # Reexecuta o update sem informar order/issue_pid_suffix: os valores
        # já existentes devem ser preservados, não recalculados.
        issue.update(
            self.user,
            self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
        )
        self.assertEqual(issue.order, 7)
        self.assertEqual(issue.issue_pid_suffix, "0007")

    def test_update_changes_number_to_none_in_place(self):
        """
        Regressão do bug #1024: ao atualizar um Issue existente, mudar o
        número do fascículo para None deve alterar o próprio registro,
        e não criar um novo.
        """
        issue = Issue()
        issue.update(
            self.user,
            self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
        )
        issue_pk = issue.pk
        self.assertEqual(Issue.objects.count(), 1)

        issue.update(
            self.user,
            self.journal,
            volume="49",
            supplement=None,
            number=None,
            publication_year="2025",
        )

        self.assertEqual(issue.pk, issue_pk)
        self.assertIsNone(issue.number)
        self.assertEqual(Issue.objects.count(), 1)

    def test_update_raises_issue_update_error_on_unexpected_exception(self):
        issue = Issue()
        with mock.patch.object(Issue, "save", side_effect=ValueError("boom")):
            with self.assertRaises(IssueUpdateError):
                issue.update(
                    self.user,
                    self.journal,
                    volume="49",
                    supplement=None,
                    number="1",
                    publication_year="2025",
                )

    def test_update_reraises_integrity_error_without_wrapping(self):
        issue = Issue()
        with mock.patch.object(Issue, "save", side_effect=IntegrityError("dup")):
            with self.assertRaises(IntegrityError):
                issue.update(
                    self.user,
                    self.journal,
                    volume="49",
                    supplement=None,
                    number="1",
                    publication_year="2025",
                )


class IssueCreateOrUpdateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="user1", password="pass")
        cls.journal = Journal.objects.create(creator=cls.user, journal_acron="jacron")

    def test_create_or_update_creates_when_not_found(self):
        issue = Issue.create_or_update(
            self.user,
            journal=self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
        )
        self.assertIsNotNone(issue.pk)
        self.assertEqual(Issue.objects.count(), 1)

    def test_create_or_update_updates_when_found_by_same_attributes(self):
        first = Issue.create_or_update(
            self.user,
            journal=self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
            total_documents=10,
        )
        second = Issue.create_or_update(
            self.user,
            journal=self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
            total_documents=15,
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Issue.objects.count(), 1)
        second.refresh_from_db()
        self.assertEqual(second.total_documents, 15)

    def test_create_or_update_creates_duplicate_when_search_attributes_change(self):
        """
        Documenta a limitação do create_or_update isolado: como a busca usa
        os NOVOS valores de volume/número/suplemento, uma mudança nesses
        valores (ex.: número virando None) não encontra o registro original
        e cria um segundo Issue.

        Este é exatamente o cenário do bug #1024. A correção definitiva não
        está neste método, e sim em migration/controller.py, que passa a
        chamar issue.update() diretamente sobre o Issue já vinculado ao
        IssueProc, em vez de rotear a atualização por create_or_update().
        """
        first = Issue.create_or_update(
            self.user,
            journal=self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
        )
        second = Issue.create_or_update(
            self.user,
            journal=self.journal,
            volume="49",
            supplement=None,
            number=None,
            publication_year="2025",
        )
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(Issue.objects.count(), 2)

    def test_reusing_existing_instance_update_avoids_duplicate(self):
        """
        Contraponto ao teste acima: quando o chamador já possui a referência
        ao Issue (como faz migration/controller.py via issue_proc.issue),
        chamar issue.update() diretamente evita a duplicidade.
        """
        issue = Issue.create_or_update(
            self.user,
            journal=self.journal,
            volume="49",
            supplement=None,
            number="1",
            publication_year="2025",
        )
        issue.update(
            self.user,
            self.journal,
            volume="49",
            supplement=None,
            number=None,
            publication_year="2025",
        )
        self.assertEqual(Issue.objects.count(), 1)
        issue.refresh_from_db()
        self.assertIsNone(issue.number)


class IssueGenerateOrderTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="user1", password="pass")
        cls.journal = Journal.objects.create(creator=cls.user, journal_acron="jacron")

    def _issue(self, **kwargs):
        return Issue(journal=self.journal, **kwargs)

    def test_generate_order_with_supplement(self):
        issue = self._issue(volume="49", number=None, supplement="2")
        self.assertEqual(issue.generate_order(), 1002)

    def test_generate_order_without_number_returns_one(self):
        issue = self._issue(volume="49", number=None, supplement=None)
        self.assertEqual(issue.generate_order(), 1)

    def test_generate_order_with_spe_number(self):
        issue = self._issue(volume="49", number="spe3", supplement=None)
        self.assertEqual(issue.generate_order(), 2003)

    def test_generate_order_ahead(self):
        issue = self._issue(volume="49", number="ahead", supplement=None)
        self.assertEqual(issue.generate_order(), 9999)

    def test_generate_order_regular_number(self):
        issue = self._issue(volume="49", number="4", supplement=None)
        self.assertEqual(issue.generate_order(), 4)

    def test_generate_issue_pid_suffix_pads_to_four_digits(self):
        issue = self._issue(volume="49", number="4", supplement=None)
        self.assertEqual(issue.generate_issue_pid_suffix(), "0004")


class IssuePropertiesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="user1", password="pass")
        cls.journal = Journal.objects.create(creator=cls.user, journal_acron="jacron")

    def test_issue_folder_combines_volume_number_supplement(self):
        issue = Issue(journal=self.journal, volume="49", number="1", supplement="2")
        self.assertEqual(issue.issue_folder, "v49n1s2")

    def test_issue_folder_omits_missing_parts(self):
        issue = Issue(journal=self.journal, volume="49", number=None, supplement=None)
        self.assertEqual(issue.issue_folder, "v49")

    def test_bundle_id_suffix_ahead(self):
        issue = Issue(
            journal=self.journal,
            publication_year="2025",
            volume="49",
            number="ahead",
            supplement=None,
        )
        self.assertEqual(issue.bundle_id_suffix, "aop")

    def test_bundle_id_suffix_regular(self):
        issue = Issue(
            journal=self.journal,
            publication_year="2025",
            volume="49",
            number="1",
            supplement=None,
        )
        self.assertEqual(issue.bundle_id_suffix, "2025-v49-n1")


class IssueGetDuplicatesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="user1", password="pass")
        cls.journal = Journal.objects.create(creator=cls.user, journal_acron="jacron")
        cls.other_journal = Journal.objects.create(creator=cls.user, journal_acron="jacron")

    def test_get_duplicates_detects_repeated_attribute_set(self):
        for year in ("2024", "2025"):
            Issue.objects.create(
                journal=self.journal,
                volume="49",
                number=None,
                supplement=None,
                publication_year=year,
                creator=self.user,
            )
        Issue.objects.create(
            journal=self.other_journal,
            volume="49",
            number=None,
            supplement=None,
            publication_year="2025",
            creator=self.user,
        )

        duplicates = list(Issue.get_duplicates(journal=self.journal))
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["count"], 2)

    def test_get_duplicates_without_journal_filter_scans_all(self):
        for _ in range(2):
            Issue.objects.create(
                journal=self.journal,
                volume="49",
                number=None,
                supplement=None,
                publication_year="2025",
                creator=self.user,
            )
        duplicates = list(Issue.get_duplicates())
        self.assertTrue(any(d["count"] > 1 for d in duplicates))


class TOCTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="user1", password="pass")
        cls.journal = Journal.objects.create(creator=cls.user, journal_acron="jacron")
        cls.issue = Issue.objects.create(
            journal=cls.journal,
            volume="49",
            number="1",
            supplement=None,
            publication_year="2025",
            creator=cls.user,
        )

    def test_create_or_update_creates_when_not_found(self):
        toc = TOC.create_or_update(self.user, self.issue, ordered=True)
        self.assertIsNotNone(toc.pk)
        self.assertTrue(toc.ordered)

    def test_create_or_update_updates_when_found(self):
        first = TOC.create_or_update(self.user, self.issue, ordered=True)
        second = TOC.create_or_update(self.user, self.issue, ordered=False)
        self.assertEqual(first.pk, second.pk)
        self.assertFalse(TOC.objects.get(pk=first.pk).ordered)


class TocSectionCreateGroupTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="user1", password="pass")
        cls.journal = Journal.objects.create(creator=cls.user, journal_acron="jacron")
        cls.issue = Issue.objects.create(
            journal=cls.journal,
            volume="49",
            number="1",
            supplement=None,
            publication_year="2025",
            creator=cls.user,
        )

    def test_create_group_generates_unique_group_code(self):
        # Depende de journal.first_letters existir no modelo real de Journal.
        group = TocSection.create_group(self.issue)
        self.assertTrue(group)
        self.assertNotIn(" ", group)
