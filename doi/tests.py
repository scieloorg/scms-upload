"""
Tests for Crossref DOI deposit functionality.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from doi.models import (
    CrossrefConfiguration,
    CrossrefDeposit,
    CrossrefDepositStatus,
    XMLCrossRef,
)

User = get_user_model()


class CrossrefConfigurationModelTest(TestCase):
    """Tests for CrossrefConfiguration model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="pass"
        )
        # Create minimal required objects for Journal
        from journal.models import Journal, OfficialJournal

        self.official_journal = OfficialJournal.objects.create(
            title="Test Journal",
            creator=self.user,
        )
        self.journal = Journal.objects.create(
            official_journal=self.official_journal,
            title="Test Journal",
            creator=self.user,
        )

    def test_create_crossref_configuration(self):
        """Test creating a CrossrefConfiguration."""
        config = CrossrefConfiguration.create_or_update(
            user=self.user,
            journal=self.journal,
            depositor_name="Test Depositor",
            depositor_email="depositor@test.com",
            registrant="Test Publisher",
        )
        self.assertEqual(config.journal, self.journal)
        self.assertEqual(config.depositor_name, "Test Depositor")
        self.assertEqual(config.depositor_email, "depositor@test.com")
        self.assertEqual(config.registrant, "Test Publisher")

    def test_create_or_update_idempotent(self):
        """Test that create_or_update is idempotent."""
        config1 = CrossrefConfiguration.create_or_update(
            user=self.user,
            journal=self.journal,
            depositor_name="Depositor 1",
            depositor_email="depositor1@test.com",
            registrant="Publisher 1",
        )
        config2 = CrossrefConfiguration.create_or_update(
            user=self.user,
            journal=self.journal,
            depositor_name="Depositor 2",
            depositor_email="depositor2@test.com",
            registrant="Publisher 2",
        )
        self.assertEqual(config1.pk, config2.pk)
        config2.refresh_from_db()
        self.assertEqual(config2.depositor_name, "Depositor 2")

    def test_crossref_configuration_str(self):
        """Test string representation."""
        config = CrossrefConfiguration.create_or_update(
            user=self.user,
            journal=self.journal,
            depositor_name="Test Depositor",
            depositor_email="depositor@test.com",
            registrant="Test Publisher",
        )
        self.assertIn("CrossrefConfiguration", str(config))

    def test_get_crossref_configuration(self):
        """Test getting CrossrefConfiguration by journal."""
        CrossrefConfiguration.create_or_update(
            user=self.user,
            journal=self.journal,
            depositor_name="Test Depositor",
            depositor_email="depositor@test.com",
            registrant="Test Publisher",
        )
        config = CrossrefConfiguration.get(journal=self.journal)
        self.assertEqual(config.journal, self.journal)

    def test_get_nonexistent_raises(self):
        """Test that getting non-existent config raises DoesNotExist."""
        with self.assertRaises(CrossrefConfiguration.DoesNotExist):
            CrossrefConfiguration.get(journal=self.journal)

    def test_create_with_crossmark_fields(self):
        """Test creating config with crossmark policy fields."""
        config = CrossrefConfiguration.create_or_update(
            user=self.user,
            journal=self.journal,
            depositor_name="Test Depositor",
            depositor_email="depositor@test.com",
            registrant="Test Publisher",
            crossmark_policy_url="https://example.com/crossmark",
            crossmark_policy_doi="10.1234/crossmark-policy",
        )
        self.assertEqual(config.crossmark_policy_url, "https://example.com/crossmark")
        self.assertEqual(config.crossmark_policy_doi, "10.1234/crossmark-policy")

    def test_create_with_credentials(self):
        """Test creating config with Crossref API credentials."""
        config = CrossrefConfiguration.create_or_update(
            user=self.user,
            journal=self.journal,
            depositor_name="Test Depositor",
            depositor_email="depositor@test.com",
            registrant="Test Publisher",
            login_id="my_crossref_id",
            login_password="my_crossref_password",
        )
        self.assertEqual(config.login_id, "my_crossref_id")
        self.assertEqual(config.login_password, "my_crossref_password")


class CrossrefDepositModelTest(TestCase):
    """Tests for CrossrefDeposit model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="pass"
        )
        from journal.models import Journal, OfficialJournal
        from article.models import Article

        self.official_journal = OfficialJournal.objects.create(
            title="Test Journal",
            creator=self.user,
        )
        self.journal = Journal.objects.create(
            official_journal=self.official_journal,
            title="Test Journal",
            creator=self.user,
        )
        self.article = Article.objects.create(
            pid_v3="S1234-56782024000100001",
            creator=self.user,
            journal=self.journal,
        )

    def test_create_deposit(self):
        """Test creating a CrossrefDeposit."""
        deposit = CrossrefDeposit.create(user=self.user, article=self.article)
        self.assertEqual(deposit.article, self.article)
        self.assertEqual(deposit.status, CrossrefDepositStatus.PENDING)

    def test_mark_submitted(self):
        """Test marking a deposit as submitted."""
        deposit = CrossrefDeposit.create(user=self.user, article=self.article)
        deposit.mark_submitted(batch_id="batch_123")
        deposit.refresh_from_db()
        self.assertEqual(deposit.status, CrossrefDepositStatus.SUBMITTED)
        self.assertEqual(deposit.batch_id, "batch_123")

    def test_mark_success(self):
        """Test marking a deposit as successful."""
        deposit = CrossrefDeposit.create(user=self.user, article=self.article)
        deposit.mark_success(response_status=200, response_body="<html>Submitted</html>")
        deposit.refresh_from_db()
        self.assertEqual(deposit.status, CrossrefDepositStatus.SUCCESS)
        self.assertEqual(deposit.response_status, 200)

    def test_mark_error(self):
        """Test marking a deposit as error."""
        deposit = CrossrefDeposit.create(user=self.user, article=self.article)
        deposit.mark_error(response_status=500, response_body="Server error")
        deposit.refresh_from_db()
        self.assertEqual(deposit.status, CrossrefDepositStatus.ERROR)
        self.assertEqual(deposit.response_status, 500)
        self.assertEqual(deposit.response_body, "Server error")

    def test_deposit_str(self):
        """Test string representation."""
        deposit = CrossrefDeposit.create(user=self.user, article=self.article)
        self.assertIn("CrossrefDeposit", str(deposit))

    def test_create_with_xml_content(self):
        """Test creating a deposit with XML content."""
        xml_content = '<?xml version="1.0"?><doi_batch/>'
        deposit = CrossrefDeposit.create(
            user=self.user, article=self.article, xml_content=xml_content
        )
        self.assertIsNotNone(deposit.xml_crossref)
        self.assertEqual(deposit.xml_crossref.creator, self.user)


class CrossrefControllerTest(TestCase):
    """Tests for doi.controller functions."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="pass"
        )
        from journal.models import Journal, OfficialJournal
        from article.models import Article

        self.official_journal = OfficialJournal.objects.create(
            title="Test Journal",
            creator=self.user,
        )
        self.journal = Journal.objects.create(
            official_journal=self.official_journal,
            title="Test Journal",
            journal_acron="testj",
            creator=self.user,
        )
        self.article = Article.objects.create(
            pid_v3="S1234-56782024000100001",
            creator=self.user,
            journal=self.journal,
        )
        self.config = CrossrefConfiguration.create_or_update(
            user=self.user,
            journal=self.journal,
            depositor_name="Test Depositor",
            depositor_email="depositor@test.com",
            registrant="Test Publisher",
            login_id="test_login",
            login_password="test_password",
        )

    def test_deposit_article_doi_without_sps_pkg(self):
        """Test that deposit raises error when article has no sps_pkg."""
        from doi.controller import CrossrefDepositError, deposit_article_doi

        with self.assertRaises(CrossrefDepositError):
            deposit_article_doi(user=self.user, article=self.article)

    def test_deposit_article_doi_without_config(self):
        """Test that deposit raises error when no Crossref config exists."""
        from doi.controller import (
            CrossrefConfigurationNotFoundError,
            deposit_article_doi,
        )
        from article.models import Article

        article_no_config = Article.objects.create(
            pid_v3="S9999-99992024000100001",
            creator=self.user,
        )

        with self.assertRaises(CrossrefDepositError):
            deposit_article_doi(user=self.user, article=article_no_config)

    def test_deposit_article_doi_no_journal(self):
        """Test that deposit raises error when article has no journal."""
        from doi.controller import CrossrefDepositError, deposit_article_doi
        from article.models import Article

        article = Article.objects.create(
            pid_v3="S9999-00002024000100001",
            creator=self.user,
        )
        with self.assertRaises(CrossrefDepositError):
            deposit_article_doi(user=self.user, article=article)

    @patch("doi.controller.deposit_xml_to_crossref")
    @patch("doi.controller.get_crossref_xml")
    def test_deposit_article_doi_success(self, mock_get_xml, mock_deposit):
        """Test successful DOI deposit."""
        from doi.controller import deposit_article_doi
        from package.models import SPSPkg

        mock_get_xml.return_value = "<?xml version='1.0'?><doi_batch/>"
        mock_deposit.return_value = (200, "<html>Submitted successfully</html>")

        sps_pkg = SPSPkg.objects.create(
            pid_v3="S1234-56782024000100001",
            sps_pkg_name="test-pkg",
            creator=self.user,
        )
        self.article.sps_pkg = sps_pkg
        self.article.save()

        deposit = deposit_article_doi(user=self.user, article=self.article)

        self.assertEqual(deposit.status, CrossrefDepositStatus.SUCCESS)
        self.assertEqual(deposit.response_status, 200)
        mock_get_xml.assert_called_once_with(sps_pkg, self.config)
        mock_deposit.assert_called_once()

    @patch("doi.controller.deposit_xml_to_crossref")
    @patch("doi.controller.get_crossref_xml")
    def test_deposit_article_doi_no_redeposit_without_force(
        self, mock_get_xml, mock_deposit
    ):
        """Test that successful deposit is not re-deposited without force=True."""
        from doi.controller import deposit_article_doi
        from package.models import SPSPkg

        mock_get_xml.return_value = "<?xml version='1.0'?><doi_batch/>"
        mock_deposit.return_value = (200, "<html>Submitted successfully</html>")

        sps_pkg = SPSPkg.objects.create(
            pid_v3="S1234-56782024000100001",
            sps_pkg_name="test-pkg",
            creator=self.user,
        )
        self.article.sps_pkg = sps_pkg
        self.article.save()

        deposit1 = deposit_article_doi(user=self.user, article=self.article)
        self.assertEqual(deposit1.status, CrossrefDepositStatus.SUCCESS)

        # Re-deposit without force
        deposit2 = deposit_article_doi(user=self.user, article=self.article)
        self.assertEqual(deposit2.pk, deposit1.pk)

        # Only called once
        self.assertEqual(mock_deposit.call_count, 1)

    def test_deposit_xml_without_credentials(self):
        """Test that deposit_xml raises error without credentials."""
        from doi.controller import CrossrefDepositError, deposit_xml_to_crossref

        config_no_creds = CrossrefConfiguration.create_or_update(
            user=self.user,
            journal=self.journal,
            depositor_name="Test Depositor",
            depositor_email="depositor@test.com",
            registrant="Test Publisher",
        )

        with self.assertRaises(CrossrefDepositError) as ctx:
            deposit_xml_to_crossref("<?xml?>", config_no_creds)

        self.assertIn("credentials", str(ctx.exception).lower())
