import logging
from datetime import datetime
from unittest import mock
from unittest.mock import ANY, MagicMock, Mock, call, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from lxml import etree

from pid_requester import exceptions, models
from packtools.sps.pid_provider.xml_sps_adapter import PidProviderXMLAdapter
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

User = get_user_model()


def _get_xml_adapter_from_file(path):
    for item in XMLWithPre.create(path=path):
        obj = PidProviderXMLAdapter(item)
        return obj


def _get_xml_with_pre(xml=None):
    xml = xml or "<article/>"
    return XMLWithPre("", etree.fromstring(xml))


def _get_xml_adapter(xml=None):
    xml = xml or "<article/>"
    xml_with_pre = XMLWithPre("", etree.fromstring(xml))
    obj = PidProviderXMLAdapter(xml_with_pre)
    return obj


def _get_xml_adapter_with_issue_data():
    xml_adapter = _get_xml_adapter()
    xml_adapter.journal_issn_electronic = "data-issn-e"
    xml_adapter.journal_issn_print = "data-issn-p"
    xml_adapter.volume = "data-vol"
    xml_adapter.number = "data-num"
    xml_adapter.suppl = "data-suppl"
    xml_adapter.pub_year = "data-year"
    xml_adapter.issue = models.XMLIssue.get_or_create(
        models.XMLJournal.get_or_create("data-issn-e", "data-issn-p"),
        "data-vol",
        "data-num",
        "data-suppl",
        "data-year",
    )
    xml_adapter.fpage = "data-fpage"
    xml_adapter.fpage_seq = "data-fpage-seq"
    xml_adapter.lpage = "data-lpage"

    xml_adapter.article_pub_year = "data-pub-year"
    xml_adapter.v3 = "123456789012345678901v3"
    xml_adapter.v2 = "123456789012345678901v2"
    xml_adapter.aop_pid = "12345678901234567890aop"

    xml_adapter.main_doi = "data-main_doi"
    xml_adapter.main_toc_section = "data-main_toc_section"
    xml_adapter.elocation_id = "data-elocation_id"
    return xml_adapter


def _create_xml_adapter__aop():
    xml_adapter = _get_xml_adapter()
    xml_adapter.journal_issn_electronic = "data-issn-e"
    xml_adapter.journal_issn_print = "data-issn-p"
    xml_adapter.issue = None
    xml_adapter.article_pub_year = "data-pub-year"
    xml_adapter.v3 = "123456789012345678901v3"
    xml_adapter.v2 = "123456789012345678901v2"
    xml_adapter.aop_pid = "12345678901234567890aop"
    xml_adapter.main_doi = "data-main_doi"
    xml_adapter.main_toc_section = "data-main_toc_section"
    return xml_adapter


class PidRequesterXMLValidateQueryParamsTest(TestCase):
    def setUp(self):
        self.article_params = {
            "z_article_titles_texts": "TITLES",
            "z_collab": "VALUE",
            "z_links": "Links",
            "z_partial_body": "Body",
            "z_surnames": "Z_SURNAMES",
            "article_pub_year": "2020",
            "elocation_id": "e19347",
            "journal__issn_electronic": "issn electronic",
            "journal__issn_print": "issn print",
            "main_doi": "DOI",
            "pkg_name": "pkgName",
        }

        self.issue_params = {
            "issue__pub_year": "year",
            "issue__volume": "vol",
            "issue__number": "num",
            "issue__suppl": "suppl",
            "fpage": "1",
            "fpage_seq": "a",
            "lpage": "11",
        }

    def test_validate_query_params_all_present(self):
        params = self.article_params
        result = models.PidRequesterXML.validate_query_params(params)
        self.assertTrue(result)

    def test_validate_query_params_all_present_plus_issue_params(self):
        params = self.article_params
        params.update(self.issue_params)
        result = models.PidRequesterXML.validate_query_params(params)
        self.assertTrue(result)

    def test_validate_query_params_issue_params_only(self):
        params = {}
        params.update(self.issue_params)
        with self.assertRaises(exceptions.NotEnoughParametersToGetDocumentRecordError):
            result = models.PidRequesterXML.validate_query_params(params)

    def test_validate_query_params_journal_issns_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["journal__issn_print"]
        del params["journal__issn_electronic"]
        with self.assertRaises(exceptions.NotEnoughParametersToGetDocumentRecordError):
            result = models.PidRequesterXML.validate_query_params(params)

    def test_validate_query_params_pub_year_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["article_pub_year"]
        del params["issue__pub_year"]
        with self.assertRaises(exceptions.NotEnoughParametersToGetDocumentRecordError):
            result = models.PidRequesterXML.validate_query_params(params)

    def test_validate_query_params_main_doi_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["main_doi"]
        result = models.PidRequesterXML.validate_query_params(params)
        self.assertTrue(result)

    def test_validate_query_params_fpage_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["fpage"]
        result = models.PidRequesterXML.validate_query_params(params)
        self.assertTrue(result)

    def test_validate_query_params_elocation_id_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["elocation_id"]
        result = models.PidRequesterXML.validate_query_params(params)
        self.assertTrue(result)

    def test_validate_query_params_main_doi_fpage_elocation_id_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["main_doi"]
        del params["fpage"]
        del params["elocation_id"]
        result = models.PidRequesterXML.validate_query_params(params)
        self.assertTrue(result)

    def test_validate_query_params_z_surnames_id_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["main_doi"]
        del params["fpage"]
        del params["elocation_id"]
        del params["z_surnames"]
        result = models.PidRequesterXML.validate_query_params(params)
        self.assertTrue(result)

    def test_validate_query_params_z_collab_id_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["main_doi"]
        del params["fpage"]
        del params["elocation_id"]
        del params["z_collab"]
        result = models.PidRequesterXML.validate_query_params(params)
        self.assertTrue(result)

    def test_validate_query_params_z_collab_id_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["main_doi"]
        del params["fpage"]
        del params["elocation_id"]
        del params["z_links"]
        result = models.PidRequesterXML.validate_query_params(params)
        self.assertTrue(result)

    def test_validate_query_params_z_collab_id_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["main_doi"]
        del params["fpage"]
        del params["elocation_id"]
        del params["pkg_name"]
        result = models.PidRequesterXML.validate_query_params(params)
        self.assertTrue(result)

    def test_validate_query_params_z_collab_id_absence(self):
        params = self.article_params
        params.update(self.issue_params)
        del params["main_doi"]
        del params["fpage"]
        del params["elocation_id"]
        del params["pkg_name"]
        del params["z_surnames"]
        del params["z_collab"]
        del params["z_links"]

        with self.assertRaises(exceptions.NotEnoughParametersToGetDocumentRecordError):
            result = models.PidRequesterXML.validate_query_params(params)


@patch(
    "packtools.sps.pid_provider.xml_sps_adapter.PidProviderXMLAdapter.query_list",
    new_callable=mock.PropertyMock,
)
@patch(
    "pid_requester.models.PidRequesterXML.validate_query_params",
    return_value=True,
)
@patch("pid_requester.models.PidRequesterXML.objects.get")
class PidRequesterXMLQueryDocumentTest(TestCase):
    def test_query_document_is_called_with_query_params(
        self,
        mock_get,
        mock_validate_params,
        mock_query_list,
    ):
        """
        PidRequesterXML._query_document is called with parameters returned by
        PidRequesterXML.query_list
        """
        params_list = [
            {"key": "value"},
        ]
        mock_query_list.return_value = params_list
        mock_get.side_effect = models.PidRequesterXML.DoesNotExist
        xml_adapter = _get_xml_adapter()
        result = models.PidRequesterXML._query_document(xml_adapter)
        mock_get.assert_called_once_with(**{"key": "value"})

    def test_query_document_returns_none_if_document_does_not_exist(
        self,
        mock_get,
        mock_validate_params,
        mock_query_list,
    ):
        params_list = [
            {"key": "value"},
        ]
        mock_query_list.return_value = params_list
        mock_get.side_effect = models.PidRequesterXML.DoesNotExist
        xml_adapter = _get_xml_adapter()
        result = models.PidRequesterXML._query_document(xml_adapter)
        self.assertIsNone(result)

    def test_query_document_returns_found_document(
        self,
        mock_get,
        mock_validate_params,
        mock_query_list,
    ):
        params_list = [
            {"key": "value"},
        ]
        mock_query_list.return_value = params_list
        mock_get.return_value = models.PidRequesterXML()
        xml_adapter = _get_xml_adapter()
        result = models.PidRequesterXML._query_document(xml_adapter)
        self.assertEqual(models.PidRequesterXML, type(result))

    def test_query_document_returns_found_item_at_the_second_round(
        self,
        mock_get,
        mock_validate_params,
        mock_query_list,
    ):
        params_list = [
            {"key": "value"},
            {"key": "value2"},
        ]
        mock_query_list.return_value = params_list
        mock_get.side_effect = [
            models.PidRequesterXML.DoesNotExist,
            models.PidRequesterXML(),
        ]
        xml_adapter = _get_xml_adapter()
        result = models.PidRequesterXML._query_document(xml_adapter)
        self.assertEqual(models.PidRequesterXML, type(result))

    def test_query_document_raises_query_document_error_because_multiple_objects_returned(
        self,
        mock_get,
        mock_validate_params,
        mock_query_list,
    ):
        params_list = [
            {"key": "value"},
        ]
        mock_query_list.return_value = params_list
        mock_get.side_effect = models.PidRequesterXML.MultipleObjectsReturned
        with self.assertRaises(
            exceptions.QueryDocumentMultipleObjectsReturnedError
        ) as exc:
            xml_adapter = _get_xml_adapter()
            result = models.PidRequesterXML._query_document(xml_adapter)

    def test_query_document_raises_error(
        self,
        mock_get,
        mock_validate_params,
        mock_query_list,
    ):
        """
        PidRequesterXML._query_document is called with parameters returned by
        PidRequesterXML.query_list
        """
        params_list = [
            {"key": "value"},
        ]
        mock_query_list.return_value = params_list
        mock_validate_params.side_effect = (
            exceptions.NotEnoughParametersToGetDocumentRecordError
        )

        with self.assertRaises(exceptions.NotEnoughParametersToGetDocumentRecordError):
            xml_adapter = _get_xml_adapter()
            result = models.PidRequesterXML._query_document(xml_adapter)


@patch("pid_requester.models.PidRequesterXML._query_document")
class PidRequesterXMLGetRegisteredTest(TestCase):
    def setUp(self):
        self.xml_with_pre = _get_xml_with_pre()

    def test_get_registered_returns_dict_with_registered_data(
        self,
        mock_query_document,
    ):
        pid_req_xml = models.PidRequesterXML()
        pid_req_xml.pkg_name = "registered_pkg_name"
        pid_req_xml.v2 = "registered_v2"
        pid_req_xml.v3 = "registered_v3"
        pid_req_xml.aop_pid = "registered_aop_pid"
        pid_req_xml.created = datetime(2023, 2, 20)
        pid_req_xml.updated = datetime(2023, 2, 20)

        mock_query_document.return_value = pid_req_xml

        result = models.PidRequesterXML.get_registered(self.xml_with_pre)
        expected = {
            "v3": "registered_v3",
            "v2": "registered_v2",
            "aop_pid": "registered_aop_pid",
            "pkg_name": "registered_pkg_name",
            "created": "2023-02-20T00:00:00",
            "updated": "2023-02-20T00:00:00",
            "record_status": "updated",
            "synchronized": False,
        }
        self.assertDictEqual(expected, result)

    def test_get_registered_returns_none(
        self,
        mock_query_document,
    ):
        mock_query_document.return_value = None

        result = models.PidRequesterXML.get_registered(self.xml_with_pre)
        self.assertIsNone(result)

    def test_get_registered_returns_error_multiple_return(
        self,
        mock_query_document,
    ):
        mock_query_document.side_effect = (
            exceptions.QueryDocumentMultipleObjectsReturnedError
        )

        result = models.PidRequesterXML.get_registered(self.xml_with_pre)
        self.assertIn("error_type", result.keys())
        self.assertIn("error_msg", result.keys())

    def test_get_registered_returns_error_not_enough_params(
        self,
        mock_query_document,
    ):
        mock_query_document.side_effect = (
            exceptions.NotEnoughParametersToGetDocumentRecordError
        )

        result = models.PidRequesterXML.get_registered(self.xml_with_pre)
        self.assertIn("error_type", result.keys())
        self.assertIn("error_msg", result.keys())


class PidRequesterXMLEvaluateRegistrationTest(TestCase):
    def setUp(self):
        self.xml_adapter = _get_xml_adapter()

    def test_evaluate_registration_accepts_xml_is_aop_and_registered_is_aop(self):
        registered = Mock(spec=models.PidRequesterXML)
        registered.is_aop = True

        result = models.PidRequesterXML.evaluate_registration(
            self.xml_adapter, registered
        )
        self.assertTrue(result)

    def test_evaluate_registration_accepts_xml_is_not_aop_and_registered_is_aop(self):
        registered = Mock(spec=models.PidRequesterXML)
        registered.is_aop = True

        self.xml_adapter = _get_xml_adapter_from_file(
            "./pid_requester/fixtures/sub-article/2236-8906-hoehnea-49-e1082020.xml"
        )

        result = models.PidRequesterXML.evaluate_registration(
            self.xml_adapter, registered
        )
        self.assertTrue(result)

    def test_evaluate_registration_raises_error(self):
        registered = Mock(spec=models.PidRequesterXML)
        registered.is_aop = False

        with self.assertRaises(exceptions.ForbiddenPidRequesterXMLRegistrationError):
            result = models.PidRequesterXML.evaluate_registration(
                self.xml_adapter, registered
            )


@patch("pid_requester.models.PidRequesterXML._get_unique_v2")
class PidRequesterXMLAddV2Test(TestCase):
    def _get_xml_adapter(self, v2=None, v3=None, aop_pid=None):
        v2 = (
            v2
            and f'<article-id specific-use="scielo-v2" pub-id-type="publisher-id">{v2}</article-id>'
            or ""
        )
        v3 = (
            v3
            and f'<article-id specific-use="scielo-v3" pub-id-type="publisher-id">{v3}</article-id>'
            or ""
        )
        aop_pid = (
            aop_pid
            and f'<article-id specific-use="previous-pid" pub-id-type="publisher-id">{aop_pid}</article-id>'
            or ""
        )

        return _get_xml_adapter(
            f"""<article>
            <front><article-meta>
            {v2}
            {v3}
            {aop_pid}
            <article-id pub-id-type="doi">10.36416/1806-3756/e20220072</article-id>
            <article-id pub-id-type="other">01100</article-id>
            </article-meta></front>
            </article>"""
        )

    # TODO
    # def test_add_pid_v2_uses_registered_pid_v2(
    #     self,
    #     mock_get_unique_v2,
    # ):
    #     found = models.PidRequesterXML()
    #     found.v2 = "registered_v2"

    #     xml_adapter = self._get_xml_adapter(v2='xml_v2')

    #     mock_get_unique_v2.return_value = "generated_v2"

    #     models.PidRequesterXML._add_pid_v2(xml_adapter, found)
    #     self.assertEqual("registered_v2", xml_adapter.v2)

    def test_add_pid_v2_replace_xml_v2_because_its_value_is_invalid_length_is_not_23(
        self,
        mock_get_unique_v2,
    ):
        found = models.PidRequesterXML()
        found.v2 = None

        xml_adapter = self._get_xml_adapter(v2="bad_size_not_23")

        mock_get_unique_v2.return_value = "S1806-37132022000201100"

        models.PidRequesterXML._add_pid_v2(xml_adapter, found)
        self.assertEqual("S1806-37132022000201100", xml_adapter.v2)

    def test_add_pid_v2_keeps_xml_v2(
        self,
        mock_get_unique_v2,
    ):
        found = models.PidRequesterXML()
        found.v2 = None

        xml_adapter = self._get_xml_adapter(v2="S1806-37132022000199999")

        mock_get_unique_v2.return_value = "S1806-37132022000300001"

        models.PidRequesterXML._add_pid_v2(xml_adapter, found)
        self.assertEqual("S1806-37132022000199999", xml_adapter.v2)

    def test_add_pid_v2_uses_unique_v2(
        self,
        mock_get_unique_v2,
    ):
        found = models.PidRequesterXML()
        found.v2 = None

        xml_adapter = self._get_xml_adapter()

        mock_get_unique_v2.return_value = "S1806-37132022000201100"

        models.PidRequesterXML._add_pid_v2(xml_adapter, found)
        self.assertEqual("S1806-37132022000201100", xml_adapter.v2)


class PidRequesterXMLAddAopPidTest(TestCase):
    def _get_xml_adapter(self, v2=None, v3=None, aop_pid=None):
        v2 = (
            v2
            and f'<article-id specific-use="scielo-v2" pub-id-type="publisher-id">{v2}</article-id>'
            or ""
        )
        v3 = (
            v3
            and f'<article-id specific-use="scielo-v3" pub-id-type="publisher-id">{v3}</article-id>'
            or ""
        )
        aop_pid = (
            aop_pid
            and f'<article-id specific-use="previous-pid" pub-id-type="publisher-id">{aop_pid}</article-id>'
            or ""
        )

        return _get_xml_adapter(
            f"""<article>
            <front><article-meta>
            {v2}
            {v3}
            {aop_pid}
            <article-id pub-id-type="doi">10.36416/1806-3756/e20220072</article-id>
            <article-id pub-id-type="other">01100</article-id>
            </article-meta></front>
            </article>"""
        )

    def test_add_aop_pid_uses_registered_aop_pid(
        self,
    ):
        found = models.PidRequesterXML()
        found.aop_pid = "12345678901234567890aop"

        xml_adapter = self._get_xml_adapter(aop_pid="xml_aop_pid")

        models.PidRequesterXML._add_aop_pid(xml_adapter, found)
        self.assertEqual("12345678901234567890aop", xml_adapter.aop_pid)

    def test_add_aop_pid_does_not_replace_by_none(
        self,
    ):
        found = models.PidRequesterXML()
        found.aop_pid = None

        xml_adapter = self._get_xml_adapter(aop_pid="xml_aop_pid")

        models.PidRequesterXML._add_aop_pid(xml_adapter, found)
        self.assertEqual("xml_aop_pid", xml_adapter.aop_pid)


@patch("pid_requester.models.PidRequesterXML._is_registered_pid")
@patch("pid_requester.models.PidRequesterXML._get_unique_v3")
class PidRequesterXMLAddPidV3Test(TestCase):
    def _get_xml_adapter(self, v2=None, v3=None, aop_pid=None):
        v2 = (
            v2
            and f'<article-id specific-use="scielo-v2" pub-id-type="publisher-id">{v2}</article-id>'
            or ""
        )
        v3 = (
            v3
            and f'<article-id specific-use="scielo-v3" pub-id-type="publisher-id">{v3}</article-id>'
            or ""
        )
        aop_pid = (
            aop_pid
            and f'<article-id specific-use="previous-pid" pub-id-type="publisher-id">{aop_pid}</article-id>'
            or ""
        )

        return _get_xml_adapter(
            f"""<article>
            <front><article-meta>
            {v2}
            {v3}
            {aop_pid}
            <article-id pub-id-type="doi">10.36416/1806-3756/e20220072</article-id>
            <article-id pub-id-type="other">01100</article-id>
            </article-meta></front>
            </article>"""
        )

    def test_add_pid_v3_uses_registered_v3(
        self,
        mock__get_unique_v3,
        mock__is_registered_pid,
    ):
        found = models.PidRequesterXML()
        found.v3 = "123456789012345678901v3"

        xml_adapter = self._get_xml_adapter(v3="xml_v3")

        models.PidRequesterXML._add_pid_v3(xml_adapter, found)
        self.assertEqual("123456789012345678901v3", xml_adapter.v3)

    def test_add_pid_v3_replaced_by_generated(
        self,
        mock__get_unique_v3,
        mock__is_registered_pid,
    ):
        mock__is_registered_pid.return_value = True
        mock__get_unique_v3.return_value = "gen456789012345678901v3"

        found = None

        xml_adapter = self._get_xml_adapter(v3="xml_v3")

        models.PidRequesterXML._add_pid_v3(xml_adapter, found)
        self.assertEqual("gen456789012345678901v3", xml_adapter.v3)

    def test_add_pid_v3_keeps_xml_v3(
        self,
        mock__get_unique_v3,
        mock__is_registered_pid,
    ):
        mock__is_registered_pid.return_value = False
        mock__get_unique_v3.return_value = "gen456789012345678901v3"

        found = None

        xml_adapter = self._get_xml_adapter(v3="xml456789012345678901v3")

        models.PidRequesterXML._add_pid_v3(xml_adapter, found)
        self.assertEqual("xml456789012345678901v3", xml_adapter.v3)


@patch(
    "pid_requester.models.PidRequesterXML.current_version",
    new_callable=mock.PropertyMock,
)
class PidRequesterXMLIsEqualToTest(TestCase):
    def test_is_equal_to_returns_false(self, mock_last_version):
        registered = models.PidRequesterXML()

        xml_adapter = _get_xml_adapter()

        result = registered.is_equal_to(xml_adapter)
        self.assertFalse(result)

    def test_is_equal_to_returns_true(self, mock_last_version):
        version = Mock(spec=models.XMLVersion)
        version.finger_print = (
            "fc676757308ad196fd4cebdbc6d7c1f135a68f6ed0c5d3af5f04075664ef6bb3"
        )

        mock_last_version.return_value = version

        xml_adapter = _get_xml_adapter_from_file(
            "./pid_requester/fixtures/sub-article/2236-8906-hoehnea-49-e1082020.xml"
        )
        print(xml_adapter.finger_print)

        registered = models.PidRequesterXML()
        result = registered.is_equal_to(xml_adapter)
        self.assertTrue(result)


@patch(
    "pid_requester.models.utcnow",
    side_effect=[datetime(2020, 2, 2, 0, 0), datetime(2020, 2, 3, 0, 0)],
)
@patch("pid_requester.models.PidRequest.save")
class PidRequesterXMLRegisterTest(TestCase):
    def test_register_register_bad_request_and_returns_error(
        self,
        mock_pid_request_save,
        mock_now,
    ):
        expected = {
            "result_type": "<class 'pid_requester.exceptions.NotEnoughParametersToGetDocumentRecordError'>",
            "result_msg": "No attribute enough for disambiguations {'z_surnames': None, 'z_collab': None, 'main_doi': None, 'z_links': None, 'z_partial_body': None, 'pkg_name': None, 'elocation_id': None, 'journal__issn_print': None, 'journal__issn_electronic': None, 'article_pub_year': None, 'z_article_titles_texts': None}",
        }

        user = User()
        xml_with_pre = _get_xml_with_pre()
        result = models.PidRequesterXML.register(
            xml_with_pre=xml_with_pre,
            filename="filename.xml",
            user=user,
            is_published=False,
            synchronized=None,
        )
        self.assertEqual(expected["result_type"], result["result_type"])
        self.assertIsNotNone(result["result_msg"])

    @patch("pid_requester.models.PidRequesterXML._is_registered_pid")
    @patch("pid_requester.models.PidRequesterXML.objects.get")
    @patch("pid_requester.models.PidRequesterXML.save")
    @patch("pid_requester.models.SyncFailure.create")
    @patch("pid_requester.models.XMLSPS.save")
    @patch("pid_requester.models.XMLVersion.save")
    @patch("pid_requester.models.XMLIssue.save")
    @patch("pid_requester.models.XMLJournal.save")
    def test_register_for_xml_zip_was_unable_to_get_pid_from_core(
        self,
        mock_xml_journal_save,
        mock_xml_issue_save,
        mock_xml_version_save,
        mock_xml_sps_save,
        mock_sync_failure_create,
        mock_pid_requester_xml_save,
        mock_pid_requester_xml_objects_get,
        mock_is_registered_pid,
        mock_pid_requester_bad_req_save,
        mock_now,
    ):
        # instancia os dublês
        mock_pid_requester_xml_objects_get.return_value = None
        mock_sync_failure_create.return_value = models.SyncFailure()
        mock_is_registered_pid.return_value = None

        items = XMLWithPre.create(
            path="./pid_requester/fixtures/sub-article/2236-8906-hoehnea-49-e1082020.xml"
        )
        items = list(items)
        user = User.objects.first()

        result = models.PidRequesterXML.register(
            xml_with_pre=items[0],
            filename="filename.xml",
            user=user,
            is_published=False,
            synchronized=None,
            error_type="error_type",
            error_msg="error_msg",
            traceback="traceback",
        )

        result = list(result)
        mock_sync_failure_create.assert_called_once_with(
            "error_msg",
            "error_type",
            "traceback",
            user,
        )


@patch("pid_requester.models.PidRequesterXML.is_equal_to")
@patch("pid_requester.models.PidRequesterXML._query_document")
class PidRequesterGetRegistrationDemandTest(TestCase):
    def test_check_registration_demand_requires_none(
        self,
        mock_query_document,
        mock_is_equal_to,
    ):
        mock_is_equal_to.return_value = True
        registered = MagicMock(models.PidRequesterXML)
        registered.synchronized = True
        mock_query_document.return_value = registered
        demand = models.PidRequesterXML.check_registration_demand(ANY)

        self.assertIsNotNone(demand["registered"])
        self.assertFalse(demand["required_remote_registration"])
        self.assertFalse(demand["required_local_registration"])

    def test_check_registration_demand_local_and_remote_required_for_new_record(
        self,
        mock_query_document,
        mock_is_equal_to,
    ):
        mock_is_equal_to.return_value = False
        mock_query_document.return_value = None
        demand = models.PidRequesterXML.check_registration_demand(ANY)

        self.assertDictEqual({}, demand["registered"])
        self.assertTrue(demand["required_remote_registration"])
        self.assertTrue(demand["required_local_registration"])

    def test_check_registration_demand_error(
        self,
        mock_query_document,
        mock_is_equal_to,
    ):
        mock_query_document.side_effect = (
            exceptions.NotEnoughParametersToGetDocumentRecordError(
                "NotEnoughParametersToGetDocumentRecordError"
            )
        )
        demand = models.PidRequesterXML.check_registration_demand(ANY)

        self.assertIsNotNone(demand["error_type"])
        self.assertIsNotNone(demand["error_msg"])

    def test_check_registration_demand_local_and_remote_required_for_registered_record(
        self,
        mock_query_document,
        mock_is_equal_to,
    ):
        mock_is_equal_to.return_value = True
        registered = MagicMock(models.PidRequesterXML)
        registered.synchronized = False
        mock_query_document.return_value = registered
        demand = models.PidRequesterXML.check_registration_demand(ANY)

        self.assertIsNotNone(demand["registered"])
        self.assertTrue(demand["required_remote_registration"])
        self.assertTrue(demand["required_local_registration"])

    def test_check_registration_demand_local_and_remote_required_for_updating_record(
        self,
        mock_query_document,
        mock_is_equal_to,
    ):
        mock_is_equal_to.return_value = False
        registered = MagicMock(models.PidRequesterXML)
        registered.synchronized = False
        mock_query_document.return_value = registered
        demand = models.PidRequesterXML.check_registration_demand(ANY)

        self.assertIsNotNone(demand["registered"])
        self.assertTrue(demand["required_remote_registration"])
        self.assertTrue(demand["required_local_registration"])
