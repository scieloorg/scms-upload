from unittest.mock import Mock, patch, ANY, call

from django.test import TestCase
from lxml import etree

from upload import controller, choices
from article.models import Article
from article import choices as article_choices
from issue.models import Issue
from journal.models import Journal, OfficialJournal


# Create your tests here.
class ControllerTest(TestCase):
    def test__compare_journal_and_issue_from_xml_to_journal_and_issue_from_article_journal_and_issue_differ(
        self,
    ):
        response = {"journal": "not journal", "issue": "not issue"}
        article = Mock(spec=Article)
        article.issue = "issue"
        article.journal = "journal"
        journal = "not journal"
        issue = "not issue"
        expected = {
            "error": f"{article.journal} {article.issue} (registered) differs from {journal} {issue} (XML)",
            "error_type": choices.VE_DATA_CONSISTENCY_ERROR,
        }
        controller._compare_journal_and_issue_from_xml_to_journal_and_issue_from_article(
            article, response
        )
        self.assertEqual(expected["error"], response["error"])
        self.assertEqual(expected["error_type"], response["error_type"])

    def test__compare_journal_and_issue_from_xml_to_journal_and_issue_from_article_issue_differs(
        self,
    ):
        response = {"journal": "Journal", "issue": "Not same issue"}
        article = Mock(spec=Article)
        article.issue = "Issue"
        article.journal = "Journal"
        journal = "Journal"
        issue = "Not same issue"
        expected = {
            "error": f"{article.journal} {article.issue} (registered) differs from {journal} {issue} (XML)",
            "error_type": choices.VE_DATA_CONSISTENCY_ERROR,
        }
        controller._compare_journal_and_issue_from_xml_to_journal_and_issue_from_article(
            article, response
        )
        self.assertEqual(expected["error"], response["error"])
        self.assertEqual(expected["error_type"], response["error_type"])

    def test__compare_journal_and_issue_from_xml_to_journal_and_issue_from_article_journal_differs(
        self,
    ):
        response = {"journal": "not journal", "issue": "issue"}
        article = Mock(spec=Article)
        article.issue = "issue"
        article.journal = "journal"
        journal = "not journal"
        issue = "issue"
        expected = {
            "error": f"{article.journal} (registered) differs from {journal} (XML)",
            "error_type": choices.VE_ARTICLE_JOURNAL_INCOMPATIBILITY_ERROR,
        }
        controller._compare_journal_and_issue_from_xml_to_journal_and_issue_from_article(
            article, response
        )
        self.assertEqual(expected["error"], response["error"])
        self.assertEqual(expected["error_type"], response["error_type"])

    def test__compare_journal_and_issue_from_xml_to_journal_and_issue_from_article_journal_and_issue_compatible(
        self,
    ):
        response = {"journal": "journal", "issue": "issue"}
        article = Mock(spec=Article)
        article.issue = "issue"
        article.journal = "journal"
        journal = "journal"
        issue = "issue"
        expected = {
            "package_status": choices.PS_ENQUEUED_FOR_VALIDATION,
        }
        controller._compare_journal_and_issue_from_xml_to_journal_and_issue_from_article(
            article, response
        )
        self.assertIsNone(response.get("error"))
        self.assertEqual(expected["package_status"], response["package_status"])


class CheckIssueTest(TestCase):
    @patch("upload.controller.Issue.get")
    def test_issue_exists(self, mock_issue_get):
        xmltree = etree.fromstring(
            "<article><front><article-meta>"
            "<volume>Volume</volume>"
            "<issue>Number</issue>"
            "<supplement>Suppl</supplement>"
            "</article-meta></front></article>",
        )
        instance = Issue(volume="Volume", supplement="Suppl", number="Number")
        mock_issue_get.return_value = instance
        journal = "JJJJ"
        result = controller._check_issue("origin", xmltree, journal)
        self.assertEqual({"issue": instance}, result)

    @patch("upload.controller.Issue.get")
    def test_issue_does_not_exist(self, mock_issue_get):
        xmltree = etree.fromstring(
            "<article><front><article-meta>"
            "<volume>Volume</volume>"
            "<issue>Number</issue>"
            "<supplement>Suppl</supplement>"
            "</article-meta></front></article>",
        )

        mock_issue_get.side_effect = Issue.DoesNotExist
        journal = "JJJJ"
        result = controller._check_issue("origin", xmltree, journal)
        d = {"volume": "Volume", "number": "Number", "suppl": "Suppl"}
        expected = dict(
            error=f"Issue in XML is not registered in Upload: JJJJ {d}",
            error_type=choices.VE_DATA_CONSISTENCY_ERROR,
        )
        self.assertEqual(expected["error_type"], result["error_type"])
        self.assertEqual(expected["error"], result["error"])

    @patch("upload.controller.Issue.get")
    def test_issue_absent_in_xml(self, mock_issue_get):
        xmltree = etree.fromstring(
            "<article><front><article-meta>" "</article-meta></front></article>",
        )
        journal = "JJJJ"
        result = controller._check_issue("origin", xmltree, journal)
        self.assertEqual({"issue": None}, result)

    @patch("upload.controller.UnexpectedEvent.create")
    @patch("upload.controller.Issue.get")
    def test_issue_raise_exception(self, mock_issue_get, mock_unexpected_create):
        xmltree = etree.fromstring(
            "<article><front><article-meta>"
            "<volume>Volume</volume>"
            "<issue>Number</issue>"
            "<supplement>Suppl</supplement>"
            "</article-meta></front></article>",
        )

        exc = TypeError("Erro inesperado")
        mock_issue_get.side_effect = exc

        result = controller._check_issue("origin", xmltree, journal="JJJJ")

        expected = {
            "error": "Erro inesperado",
            "error_type": choices.VE_UNEXPECTED_ERROR,
        }
        self.assertEqual(expected, result)

        mock_unexpected_create.assert_called_with(
            exception=exc,
            exc_traceback=ANY,
            detail={
                "operation": "upload.controller._check_issue",
                "detail": {"origin": "origin"},
            },
        )


class CheckJournalTest(TestCase):
    @patch("upload.controller._get_journal")
    def test_journal_exists(self, mock_journal_get):
        xmltree = etree.fromstring(
            "<article><front><journal-meta>"
            "<issn pub-type='epub'>ISSN-ELEC</issn>"
            "<issn pub-type='ppub'>ISSN-PRIN</issn>"
            "<journal-title-group><journal-title>Título do periódico</journal-title></journal-title-group>"
            "</journal-meta></front></article>",
        )
        instance = Journal()
        mock_journal_get.return_value = instance
        result = controller._check_journal("origin", xmltree)
        self.assertEqual({"journal": instance}, result)

    @patch("upload.controller._get_journal")
    def test_journal_does_not_exist(self, mock_journal_get):
        xmltree = etree.fromstring(
            "<article><front><journal-meta>"
            "<issn pub-type='epub'>ISSN-ELEC</issn>"
            "<issn pub-type='ppub'>ISSN-PRIN</issn>"
            "<journal-title-group><journal-title>Título do periódico</journal-title></journal-title-group>"
            "</journal-meta></front></article>",
        )

        mock_journal_get.side_effect = Journal.DoesNotExist
        result = controller._check_journal("origin", xmltree)
        expected = dict(
            error=f"Journal in XML is not registered in Upload: Título do periódico ISSN-ELEC (electronic) ISSN-PRIN (print)",
            error_type="article-journal-incompatibility-error",
        )
        self.assertEqual(expected["error_type"], result["error_type"])
        self.assertEqual(expected["error"], result["error"])

    @patch("upload.controller.UnexpectedEvent.create")
    @patch("upload.controller._get_journal")
    def test_journal_raise_exception(self, mock_journal_get, mock_unexpected_create):
        xmltree = etree.fromstring(
            "<article><front><journal-meta>"
            "<issn pub-type='epub'>ISSN-ELEC</issn>"
            "<issn pub-type='ppub'>ISSN-PRIN</issn>"
            "<journal-title-group><journal-title>Título do periódico</journal-title></journal-title-group>"
            "</journal-meta></front></article>",
        )

        exc = Exception("Erro inesperado")
        mock_journal_get.side_effect = exc

        result = controller._check_journal("origin", xmltree)

        expected = {
            "error": "Erro inesperado",
            "error_type": choices.VE_UNEXPECTED_ERROR,
        }
        self.assertEqual(expected, result)

        mock_unexpected_create.assert_called_with(
            exception=exc,
            exc_traceback=ANY,
            detail={
                "operation": "upload.controller._check_journal",
                "detail": {"origin": "origin"},
            },
        )


# def _get_journal(journal_title, issn_electronic, issn_print):
#     j = None
#     if issn_electronic:
#         try:
#             j = OfficialJournal.objects.get(issn_electronic=issn_electronic)
#         except OfficialJournal.DoesNotExist:
#             pass

#     if not j and issn_print:
#         try:
#             j = OfficialJournal.objects.get(issn_print=issn_print)
#         except OfficialJournal.DoesNotExist:
#             pass

#     if not j and journal_title:
#         try:
#             j = OfficialJournal.objects.get(journal_title=journal_title)
#         except OfficialJournal.DoesNotExist:
#             pass

#     if j:
#         return Journal.objects.get(official=j)
#     raise Journal.DoesNotExist(f"{journal_title} {issn_electronic} {issn_print}")


class GetJournalTest(TestCase):
    @patch("upload.controller.OfficialJournal.objects.get")
    @patch("upload.controller.Journal.objects.get")
    def test__get_journal_with_issn_e(self, mock_journal_get, mock_official_j_get):
        journal = Journal()
        official_j = OfficialJournal()
        mock_journal_get.return_value = journal
        mock_official_j_get.return_value = official_j

        result = controller._get_journal(
            journal_title=None, issn_electronic="XXXXXXX", issn_print=None
        )
        self.assertEqual(journal, result)
        mock_official_j_get.assert_called_with(issn_electronic="XXXXXXX")
        mock_journal_get.assert_called_with(official=official_j)

    @patch("upload.controller.OfficialJournal.objects.get")
    @patch("upload.controller.Journal.objects.get")
    def test__get_journal_with_issn_print(self, mock_journal_get, mock_official_j_get):
        journal = Journal()
        official_j = OfficialJournal()
        mock_journal_get.return_value = journal
        mock_official_j_get.return_value = official_j

        result = controller._get_journal(
            journal_title=None, issn_electronic=None, issn_print="XXXXXXX"
        )
        self.assertEqual(journal, result)
        mock_official_j_get.assert_called_with(issn_print="XXXXXXX")
        mock_journal_get.assert_called_with(official=official_j)

    @patch("upload.controller.OfficialJournal.objects.get")
    @patch("upload.controller.Journal.objects.get")
    def test__get_journal_with_journal_title(
        self, mock_journal_get, mock_official_j_get
    ):
        journal = Journal()
        official_j = OfficialJournal()
        mock_journal_get.return_value = journal
        mock_official_j_get.return_value = official_j

        result = controller._get_journal(
            journal_title="XXXXXXX", issn_electronic=None, issn_print=None
        )
        self.assertEqual(journal, result)
        mock_official_j_get.assert_called_with(journal_title="XXXXXXX")
        mock_journal_get.assert_called_with(official=official_j)

    @patch("upload.controller.OfficialJournal.objects.get")
    @patch("upload.controller.Journal.objects.get")
    def test__get_journal_with_issn_print_after_raise_exception_does_not_exist_for_issn_electronic(
        self, mock_journal_get, mock_official_j_get
    ):
        journal = Journal()
        official_j = OfficialJournal()
        mock_journal_get.return_value = journal
        mock_official_j_get.side_effect = [
            OfficialJournal.DoesNotExist,
            official_j,
        ]

        result = controller._get_journal(
            journal_title=None, issn_electronic="EEEEEEE", issn_print="XXXXXXX"
        )
        self.assertEqual(journal, result)
        self.assertEqual(
            mock_official_j_get.mock_calls,
            [
                call(issn_electronic="EEEEEEE"),
                call(issn_print="XXXXXXX"),
            ],
        )
        mock_journal_get.assert_called_with(official=official_j)

    @patch("upload.controller.OfficialJournal.objects.get")
    @patch("upload.controller.Journal.objects.get")
    def test__get_journal_raises_multiple_object_returned(
        self, mock_journal_get, mock_official_j_get
    ):
        journal = Journal()
        official_j = OfficialJournal()
        mock_journal_get.return_value = journal
        mock_official_j_get.side_effect = OfficialJournal.MultipleObjectsReturned

        with self.assertRaises(OfficialJournal.MultipleObjectsReturned) as exc:
            result = controller._get_journal(
                journal_title="Title", issn_electronic="EEEEEEE", issn_print="XXXXXXX"
            )
            self.assertIsNone(result)
        self.assertEqual(
            mock_official_j_get.mock_calls,
            [
                call(issn_electronic="EEEEEEE"),
            ],
        )
        mock_journal_get.assert_not_called()


@patch("upload.controller.Article")
class GetArticlePreviousStatusTest(TestCase):
    def test_get_article_previous_status_require_update(self, mock_article):
        response = {}
        article = Mock(spec=Article)
        article.status = article_choices.AS_REQUIRE_UPDATE
        result = controller._get_article_previous_status(article, response)
        self.assertEqual(article_choices.AS_REQUIRE_UPDATE, result)
        self.assertEqual(article.status, article_choices.AS_CHANGE_SUBMITTED)
        self.assertEqual(response["package_category"], choices.PC_UPDATE)

    def test_get_article_previous_status_required_erratum(self, mock_article):
        response = {}
        article = Mock(spec=Article)
        article.status = article_choices.AS_REQUIRE_ERRATUM
        result = controller._get_article_previous_status(article, response)
        self.assertEqual(article_choices.AS_REQUIRE_ERRATUM, result)
        self.assertEqual(article.status, article_choices.AS_CHANGE_SUBMITTED)
        self.assertEqual(response["package_category"], choices.PC_ERRATUM)

    def test_get_article_previous_status_not_required_erratum_and_not_require_update(
        self, mock_article
    ):
        response = {}
        article = Mock(spec=Article)
        article.status = "no matter what"
        result = controller._get_article_previous_status(article, response)
        self.assertIsNone(result)
        self.assertEqual("no matter what", article.status)
        self.assertEqual(response["package_category"], choices.PC_UPDATE)
        self.assertEqual(
            f"Unexpected package. Article has no need to be updated / corrected. Article status: no matter what",
            response["error"],
        )
        self.assertEqual(choices.VE_FORBIDDEN_UPDATE_ERROR, response["error_type"])


@patch("upload.controller._get_journal")
@patch("upload.controller.Issue.get")
@patch("upload.controller.Article.objects.get")
@patch("upload.controller.PidRequester.is_registered_xml_with_pre")
class CheckArticleAndJournalTest(TestCase):
    def test__check_article_and_journal__registered_and_allowed_to_be_updated(
        self, mock_xml_with_pre, mock_article_get, mock_issue_get, mock_journal_get
    ):

        mock_xml_with_pre.return_value = {"v3": "yjukillojhk"}

        article_instance = Mock(spec=Article)

        article_instance.status = article_choices.AS_REQUIRE_UPDATE
        mock_article_get.return_value = article_instance

        issue_instance = Mock(spec=Issue)
        issue_instance.supplement = "Suppl"
        issue_instance.number = "Number"
        issue_instance.volume = "Volume"
        mock_issue_get.return_value = issue_instance

        journal_instance = Mock(spec=Journal)
        journal_instance.issn_electronic = "ISSN-ELEC"
        journal_instance.issn_print = "ISSN-PRIN"
        mock_journal_get.return_value = journal_instance

        issue_instance.journal = journal_instance
        article_instance.issue = issue_instance
        article_instance.journal = journal_instance

        xmltree = etree.fromstring(
            "<article><front><journal-meta>"
            "<issn pub-type='epub'>ISSN-ELEC</issn>"
            "<issn pub-type='ppub'>ISSN-PRIN</issn>"
            "<journal-title-group><journal-title>Título do periódico</journal-title></journal-title-group>"
            "</journal-meta>"
            "<article-meta>"
            "<volume>Volume</volume>"
            "<issue>Number</issue>"
            "<supplement>Suppl</supplement>"
            "</article-meta>"
            "</front></article>",
        )
        xml_with_pre = controller.XMLWithPre("", xmltree)
        xml_with_pre.filename = "zzz.zip"
        result = controller._check_article_and_journal(xml_with_pre)
        self.assertIsNone(result.get("error"))
        self.assertEqual(article_instance, result["article"])
        self.assertEqual(choices.PS_ENQUEUED_FOR_VALIDATION, result["package_status"])
        self.assertEqual(choices.PC_UPDATE, result["package_category"])

    def test__check_article_and_journal__new_document(
        self, mock_xml_with_pre, mock_article_get, mock_issue_get, mock_journal_get
    ):

        mock_xml_with_pre.return_value = {}

        mock_article_get.side_effect = KeyError

        issue_instance = Mock(spec=Issue)
        mock_issue_get.return_value = issue_instance
        issue_instance.supplement = "Suppl"
        issue_instance.number = "Number"
        issue_instance.volume = "Volume"

        journal_instance = Mock(spec=Journal)
        journal_instance.issn_electronic = "ISSN-ELEC"
        journal_instance.issn_print = "ISSN-PRIN"

        mock_journal_get.return_value = journal_instance

        xmltree = etree.fromstring(
            "<article><front><journal-meta>"
            "<issn pub-type='epub'>ISSN-ELEC</issn>"
            "<issn pub-type='ppub'>ISSN-PRIN</issn>"
            "<journal-title-group><journal-title>Título do periódico</journal-title></journal-title-group>"
            "</journal-meta>"
            "<article-meta>"
            "<volume>Volume</volume>"
            "<issue>Number</issue>"
            "<supplement>Suppl</supplement>"
            "</article-meta>"
            "</front></article>",
        )
        xml_with_pre = controller.XMLWithPre("", xmltree)
        xml_with_pre.filename = "zzz.zip"
        result = controller._check_article_and_journal(xml_with_pre)
        self.assertIsNone(result.get("error"))
        self.assertIsNone(result.get("article"))
        self.assertEqual(choices.PS_ENQUEUED_FOR_VALIDATION, result["package_status"])
        self.assertEqual(choices.PC_NEW_DOCUMENT, result["package_category"])


# def _check_article_and_journal(xml_with_pre):
#     # verifica se o XML está registrado no sistema
#     response = pp.is_registered_xml_with_pre(xml_with_pre, xml_with_pre.filename)

#     # verifica se o XML é esperado
#     article_previous_status = _check_package_is_expected(response)

#     # verifica se XML já está associado a um article
#     try:
#         article = response.pop("article")
#     except KeyError:
#         article = None

#     # caso encontrado erro, sair da função
#     if response.get("error"):
#         return _handle_error(response, article, article_previous_status)

#     xmltree = xml_with_pre.xmltree

#     # verifica se journal e issue estão registrados
#     response = _check_xml_journal_and_xml_issue_are_registered(
#         xml_with_pre.filename, xmltree, response
#     )
#     # caso encontrado erro, sair da função
#     if response.get("error"):
#         return _handle_error(response, article, article_previous_status)

#     if article:
#         # verifica a consistência dos dados de journal e issue
#         # no XML e na base de dados
#         _compare_journal_and_issue_from_xml_to_journal_and_issue_from_article(article, response)
#         if response.get("error"):
#             # inconsistências encontradas
#             return _handle_error(response, article, article_previous_status)
#         else:
#             # sem problemas
#             response["package_status"] = choices.PS_ENQUEUED_FOR_VALIDATION
#             response.update({"article": article})
#             return response
#     # documento novo
#     response["package_status"] = choices.PS_ENQUEUED_FOR_VALIDATION
#     return response
