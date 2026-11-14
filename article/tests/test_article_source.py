import tempfile
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from article.models import ArticleSource
from collection.models import Collection
from pid_provider.models import PidProviderXML

User = get_user_model()

URL = "https://www.scielo.br/j/rsp/a/abc123/?format=xml"


def _xml_with_pre(v3="abc123", sps_pkg_name="0034-8910-rsp-58-01"):
    xml_with_pre = Mock()
    xml_with_pre.v3 = v3
    xml_with_pre.sps_pkg_name = sps_pkg_name
    xml_with_pre.tostring.return_value = "<article/>"
    return xml_with_pre


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
@patch("pid_provider.models.PidProviderXML.get_by_pid_v3")
@patch("pid_provider.provider.PidProvider.provide_pid_for_xml_with_pre")
@patch("article.models.XMLWithPre.create")
class ArticleSourceCreateOrUpdateTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="operator")
        self.collection = Collection.objects.create(acron="scl", creator=self.user)

    def _create_or_update(self, source_date, **kwargs):
        params = dict(
            url=URL,
            source_date=source_date,
            collection=self.collection,
            pid="S0034-89102024000100001",
            is_public=True,
            detail={"aid": "abc123"},
            expected_pid_v3="abc123",
        )
        params.update(kwargs)
        return ArticleSource.create_or_update(self.user, **params)

    def _setup(self, xml_create, provide_pid, get_by_pid_v3, v3="abc123"):
        xml_create.side_effect = lambda **kwargs: iter([_xml_with_pre(v3=v3)])
        provide_pid.return_value = {"v3": v3}
        get_by_pid_v3.return_value = PidProviderXML.objects.create(
            v3=v3, creator=self.user
        )

    def _uri_calls(self, xml_create):
        return [c for c in xml_create.call_args_list if "uri" in c.kwargs]

    def test_downloads_xml_and_registers_pid(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        self._setup(xml_create, provide_pid, get_by_pid_v3)

        obj = self._create_or_update("2024-01-31T10:01:00")

        xml_create.assert_called_once_with(uri=URL)
        self.assertEqual(obj.status, ArticleSource.StatusChoices.COMPLETED)
        self.assertEqual(obj.pid_provider_xml, get_by_pid_v3.return_value)
        # o storage acrescenta sufixo se o arquivo já existir
        self.assertTrue(
            obj.file.name.startswith(
                "article_sources/0034/8910/rsp/58/01/0034-8910-rsp-58-01"
            )
        )
        self.assertEqual(
            provide_pid.call_args.kwargs["origin_date"], "2024-01-31"
        )
        self.assertEqual(obj.source_date, "2024-01-31T10:01:00")

    def test_does_not_download_again_when_source_date_is_unchanged(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        self._setup(xml_create, provide_pid, get_by_pid_v3)
        self._create_or_update("2024-01-31T10:01:00")

        self._create_or_update("2024-01-31T10:01:00")

        self.assertEqual(len(self._uri_calls(xml_create)), 1)
        self.assertEqual(provide_pid.call_count, 1)

    def test_registers_pid_again_without_download_after_pid_failure(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        self._setup(xml_create, provide_pid, get_by_pid_v3)
        provide_pid.return_value = {"error_msg": "conflict"}
        obj = self._create_or_update("2024-01-31T10:01:00")
        self.assertEqual(obj.status, ArticleSource.StatusChoices.ERROR)

        provide_pid.return_value = {"v3": "abc123"}
        obj = self._create_or_update("2024-01-31T10:01:00")

        self.assertEqual(len(self._uri_calls(xml_create)), 1)
        self.assertEqual(obj.status, ArticleSource.StatusChoices.COMPLETED)
        self.assertNotIn("error_msg", obj.detail)

    def test_downloads_again_when_source_date_changes(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        self._setup(xml_create, provide_pid, get_by_pid_v3)
        self._create_or_update("2024-01-31T10:01:00")

        obj = self._create_or_update("2024-02-05T08:00:00")

        self.assertEqual(len(self._uri_calls(xml_create)), 2)
        self.assertEqual(provide_pid.call_count, 2)
        self.assertEqual(obj.source_date, "2024-02-05T08:00:00")

    def test_pid_v3_mismatch_marks_error_and_keeps_detail(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        self._setup(xml_create, provide_pid, get_by_pid_v3, v3="other")

        obj = self._create_or_update("2024-01-31T10:01:00")

        provide_pid.assert_not_called()
        self.assertEqual(obj.status, ArticleSource.StatusChoices.ERROR)
        self.assertIn("PID v3 mismatch", obj.detail["error_msg"])
        self.assertEqual(obj.detail["aid"], "abc123")

    def test_url_error_marks_url_error(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        from core.utils.requester import NonRetryableError

        xml_create.side_effect = NonRetryableError("404")

        obj = self._create_or_update("2024-01-31T10:01:00")

        self.assertEqual(obj.status, ArticleSource.StatusChoices.URL_ERROR)
        self.assertFalse(obj.file)

    def test_not_public_is_not_downloaded(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        obj = self._create_or_update("2024-01-31T10:01:00", is_public=False)

        xml_create.assert_not_called()
        self.assertEqual(obj.status, ArticleSource.StatusChoices.NOT_PUBLIC)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
@patch("pid_provider.models.PidProviderXML.get_by_pid_v3")
@patch("pid_provider.provider.PidProvider.provide_pid_for_xml_with_pre")
@patch("article.models.XMLWithPre.create")
class ArticleSourceProcessStoredXMLTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="operator")
        self.collection = Collection.objects.create(acron="scl", creator=self.user)

    def _stored(self, status=ArticleSource.StatusChoices.ERROR, aid="abc123"):
        obj = ArticleSource.objects.create(
            url=URL,
            source_date="2024-01-31T10:01:00",
            collection=self.collection,
            status=status,
            detail={"aid": aid, "error_msg": "old error"},
            creator=self.user,
        )
        obj.save_file("0034-8910-rsp-58-01.xml", "<article/>")
        obj.save()
        return ArticleSource.objects.get(pk=obj.pk)

    def test_registers_stored_xml_without_requesting_url(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        obj = self._stored()
        xml_create.side_effect = lambda **kwargs: iter([_xml_with_pre()])
        provide_pid.return_value = {"v3": "abc123"}
        get_by_pid_v3.return_value = PidProviderXML.objects.create(
            v3="abc123", creator=self.user
        )

        obj.process_stored_xml(self.user)

        self.assertEqual(xml_create.call_count, 1)
        self.assertIn("path", xml_create.call_args.kwargs)
        self.assertNotIn("uri", xml_create.call_args.kwargs)
        obj.refresh_from_db()
        self.assertEqual(obj.status, ArticleSource.StatusChoices.COMPLETED)
        self.assertEqual(obj.pid_provider_xml, get_by_pid_v3.return_value)
        self.assertNotIn("error_msg", obj.detail)
        self.assertEqual(
            provide_pid.call_args.kwargs["origin_date"], "2024-01-31"
        )
        self.assertEqual(provide_pid.call_args.kwargs["collection_acron"], "scl")

    def test_unreadable_stored_xml_is_not_requested_from_url(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        obj = self._stored()
        xml_create.side_effect = ValueError("invalid xml")

        obj.process_stored_xml(self.user)

        self.assertNotIn("uri", xml_create.call_args.kwargs)
        provide_pid.assert_not_called()
        obj.refresh_from_db()
        self.assertEqual(obj.status, ArticleSource.StatusChoices.XML_ERROR)

    def test_missing_file_marks_xml_error(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        obj = ArticleSource.objects.create(
            url=URL, collection=self.collection, creator=self.user
        )

        obj.process_stored_xml(self.user)

        xml_create.assert_not_called()
        obj.refresh_from_db()
        self.assertEqual(obj.status, ArticleSource.StatusChoices.XML_ERROR)
        self.assertIn("not found", obj.detail["error_msg"])

    def test_checks_pid_v3_from_detail(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        obj = self._stored(aid="expected")
        xml_create.side_effect = lambda **kwargs: iter([_xml_with_pre(v3="other")])

        obj.process_stored_xml(self.user)

        provide_pid.assert_not_called()
        obj.refresh_from_db()
        self.assertEqual(obj.status, ArticleSource.StatusChoices.ERROR)
        self.assertIn("PID v3 mismatch", obj.detail["error_msg"])

    def test_get_with_stored_xml_filters_status_file_and_collection(
        self, xml_create, provide_pid, get_by_pid_v3
    ):
        with_error = self._stored()
        self._stored(status=ArticleSource.StatusChoices.COMPLETED)
        ArticleSource.objects.create(
            url=URL + "&no-file",
            collection=self.collection,
            status=ArticleSource.StatusChoices.ERROR,
            creator=self.user,
        )
        other = Collection.objects.create(acron="arg", creator=self.user)

        self.assertEqual(
            list(ArticleSource.get_with_stored_xml().values_list("id", flat=True)),
            [with_error.id],
        )
        self.assertFalse(
            ArticleSource.get_with_stored_xml(collection_acron=other.acron).exists()
        )
