import os
import io
import zipfile
import unittest
from unittest.mock import MagicMock, Mock, patch, PropertyMock
from datetime import datetime

from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.utils import isolate_apps

from package.models import (
    now,
    get_minio_config,
    minio_push_file_content,
    update_zip_file,
    basic_xml_directory_path,
    pkg_directory_path,
    preview_page_directory_path,
    BasicXMLFile,
    SPSPkgComponent,
    SPSPkg,
    BasicXMLFileSaveError,
    XMLVersionXmlWithPreError,
    SPSPkgComponentCreateOrUpdateError,
    SPSPkgMultipleObjectReturnedException,
    MinioConfiguration,
)
from collection.models import Language
from pid_provider.models import PidProviderXML

User = get_user_model()


class UtilityFunctionsTestCase(TestCase):
    def test_now_format(self):
        result = now()
        self.assertIsInstance(result, str)
        self.assertNotIn(":", result)
        self.assertNotIn(".", result)

    @patch("files_storage.models.MinioConfiguration.get_files_storage")
    def test_get_minio_config_success(self, mock_get_files_storage):
        mock_instance = MagicMock()
        mock_get_files_storage.return_value = mock_instance
        
        result = get_minio_config()
        mock_get_files_storage.assert_called_once_with(name="website")
        self.assertEqual(result, mock_instance)

    @patch("files_storage.models.MinioConfiguration.get_files_storage")
    def test_get_minio_config_failure(self, mock_get_files_storage):
        mock_get_files_storage.side_effect = Exception("Connection error")
        with self.assertRaises(MinioConfiguration.DoesNotExist):
            get_minio_config()

    def test_minio_push_file_content_failure(self):
        mock_minio = MagicMock()
        mock_minio.fput_content.side_effect = Exception("Upload failure")
        
        res = minio_push_file_content(mock_minio, b"content", "text/xml", "file.xml")
        
        self.assertIn("error_type", res)
        self.assertEqual(res["error_msg"], "Upload failure")

    def test_update_zip_file(self):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("test.xml", "<old/>")
            zf.writestr("other.txt", "keep me")

        temp_zip = self.id() + "_test.zip"
        with open(temp_zip, "wb") as f:
            f.write(zip_buffer.getvalue())

        try:
            mock_xml_pre = MagicMock()
            mock_xml_pre.tostring.return_value = b"<new_xml/>"

            update_zip_file(temp_zip, "test.xml", mock_xml_pre)

            with zipfile.ZipFile(temp_zip, "r") as zf:
                self.assertEqual(zf.read("test.xml"), b"<new_xml/>")
                self.assertEqual(zf.read("other.txt"), b"keep me")
        finally:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)

    def test_directory_paths(self):
        class DummyInstance:
            directory_path = "custom/path"
            sps_pkg_name = "sps-pkg-v1"

        class DummyChildInstance:
            sps_pkg = DummyInstance()

        self.assertEqual(basic_xml_directory_path(DummyInstance(), "file.xml"), "custom/path/file.xml")
        self.assertEqual(basic_xml_directory_path(object(), "abc-def.xml"), "sps_pkg/abc/def/abc-def.xml")
        self.assertEqual(basic_xml_directory_path(object(), "simple.xml"), "xml/simple.xml")
        self.assertEqual(pkg_directory_path(DummyInstance(), "file.zip"), "sps_pkg/sps/pkg/v1/file.zip")
        self.assertEqual(preview_page_directory_path(DummyChildInstance(), "preview.html"), "sps_pkg/sps/pkg/v1/preview.html")


@isolate_apps("package")
class BasicXMLFileTestCase(SimpleTestCase):
    def setUp(self):
        class DummyBasicXMLFile(BasicXMLFile):
            class Meta:
                app_label = "package"

        self.xml_obj = DummyBasicXMLFile()
        self.xml_obj.file = MagicMock()
        self.xml_obj.file.path = "/tmp/test_file.xml"

    def test_str_representation(self):
        self.assertEqual(str(self.xml_obj), "/tmp/test_file.xml")

    @patch("package.models.XMLWithPre.create")
    def test_xml_with_pre_property_success(self, mock_create):
        mock_create.return_value = ["parsed_xml"]
        self.assertEqual(self.xml_obj.xml_with_pre, "parsed_xml")

    @patch("package.models.XMLWithPre.create")
    def test_xml_with_pre_property_error(self, mock_create):
        mock_create.side_effect = Exception("Parse error")
        with self.assertRaises(XMLVersionXmlWithPreError):
            _ = self.xml_obj.xml_with_pre

    @patch("package.models.delete_files")
    def test_save_and_delete_file(self, mock_delete):
        self.xml_obj.file.save = MagicMock()
        self.xml_obj.save_file("updated.xml", b"<updated/>", delete_existing=True)
        mock_delete.assert_called_with("/tmp/test_file.xml")
        self.xml_obj.file.save.assert_called_once()


class SPSPkgComponentTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.pkg = SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="pkg-01", pid_v3="v3-1234")
        self.lang = Language.objects.create(creator=self.user, code2="pt")

    def test_autocomplete_and_data(self):
        component = SPSPkgComponent.objects.create(
            creator=self.user,
            sps_pkg=self.pkg,
            basename="image.jpg",
            uri="http://example.com/image.jpg",
            component_type="asset",
            lang=self.lang,
            xml_elem_id="img1",
        )
        self.assertIn("pkg-01", component.autocomplete_label())
        self.assertIn("image.jpg", component.autocomplete_label())
        
        data = component.data
        self.assertEqual(data["basename"], "image.jpg")
        self.assertEqual(data["lang"], "pt")

    def test_get_classmethod(self):
        comp = SPSPkgComponent.objects.create(
            creator=self.user,
            sps_pkg=self.pkg,
            basename="graphic.png",
            uri="http://example.com/graphic.png",
        )
        self.assertEqual(SPSPkgComponent.get(sps_pkg=self.pkg, uri="http://example.com/graphic.png"), comp)
        self.assertEqual(SPSPkgComponent.get(sps_pkg=self.pkg, basename="graphic.png"), comp)
        with self.assertRaises(ValueError):
            SPSPkgComponent.get()

    @patch("package.models.Language.get_or_create")
    def test_create_or_update(self, mock_lang_get_or_create):
        mock_lang_get_or_create.return_value = self.lang

        comp = SPSPkgComponent.create_or_update(
            user=self.user,
            sps_pkg=self.pkg,
            uri="http://example.com/file.pdf",
            basename="file.pdf",
            component_type="rendition",
            lang="pt",
        )

        self.assertEqual(comp.sps_pkg, self.pkg)
        self.assertEqual(comp.basename, "file.pdf")
        self.assertEqual(comp.creator, self.user)

        comp_updated = SPSPkgComponent.create_or_update(
            user=self.user,
            sps_pkg=self.pkg,
            uri="http://example.com/file.pdf",
            basename="file.pdf",
            component_type="updated_rendition",
        )
        self.assertEqual(comp_updated.id, comp.id)
        self.assertEqual(comp_updated.updated_by, self.user)
        self.assertEqual(comp_updated.component_type, "updated_rendition")


class SPSPkgTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pkguser", password="password")
        self.pkg = SPSPkg.objects.create(
            creator=self.user,
            sps_pkg_name="sps-12345-v1",
            pid_v3="v3-00001",
            pid_v2="v2-00001",
            registered_in_core=True,
            texts={"xml_langs": ["en"], "pdf_langs": ["en"]},
        )

    def test_fix_sps_pkg_name(self):
        with patch.object(SPSPkg, "xml_with_pre", new_callable=PropertyMock) as mock_xml_pre:
            mock_obj = MagicMock()
            mock_obj.sps_pkg_name = "sps-12345-v2"
            mock_xml_pre.return_value = mock_obj

            res = self.pkg.fix_sps_pkg_name(save=True)
            self.assertTrue(res)
            self.assertEqual(self.pkg.sps_pkg_name, "sps-12345-v2")

    def test_raises_type_error(self):
        with self.assertRaises(TypeError):
            SPSPkg.get(pid_v3="v3-00001")

    def test_get_method_single_object(self):
        found = SPSPkg.get(123, pid_v3="v3-00001")
        self.assertEqual(found, self.pkg)

    def test_validate(self):
        self.pkg.texts = {"xml_langs": ["pt", "en"], "pdf_langs": ["pt", "en"]}
        self.pkg.validate(save=True)
        self.assertTrue(self.pkg.valid_texts)

        self.pkg.texts = {"xml_langs": ["pt", "en"], "pdf_langs": ["pt"]}
        self.pkg.validate(save=True)
        self.assertFalse(self.pkg.valid_texts)

    def test_subdir_property(self):
        self.pkg.sps_pkg_name = "123456789-extra-path"
        self.assertEqual(self.pkg.subdir, os.path.join("123456789", "extra/path"))

    @patch("package.models.minio_push_file_content")
    def test_upload_to_the_cloud(self, mock_push):
        mock_push.return_value = {"uri": "http://minio.local/file.png"}
        mock_minio = MagicMock()

        res = self.pkg.upload_to_the_cloud(
            user=self.user,
            minio=mock_minio,
            filename="test.png",
            ext=".png",
            content=b"bytes",
            component_type="asset",
        )

        self.assertEqual(res["uri"], "http://minio.local/file.png")
        self.assertTrue(SPSPkgComponent.objects.filter(basename="test.png").exists())

    @patch.object(SPSPkg, "upload_to_the_cloud")
    def test_upload_xml_to_the_cloud(self, mock_upload):
        mock_upload.return_value = {"uri": "http://minio.local/file.xml"}
        
        mock_xml_pre = MagicMock()
        mock_xml_pre.xmltree = MagicMock()
        mock_xml_pre.tostring.return_value = "<xml/>"
        
        mock_minio = MagicMock()

        res = self.pkg.upload_xml_to_the_cloud(self.user, mock_minio, mock_xml_pre)
        self.assertEqual(self.pkg.xml_uri, "http://minio.local/file.xml")
        self.assertEqual(res, {"items": [{"uri": "http://minio.local/file.xml"}]})

    @patch.object(SPSPkg, "xml_with_pre", new_callable=PropertyMock)
    def test_pub_date(self, mock_xml_pre):
        mock_obj = MagicMock()
        mock_obj.article_publication_date = "2023-05-20"
        mock_xml_pre.return_value = mock_obj

        self.assertEqual(self.pkg.pub_date, "2023-05-20")

        mock_obj.article_publication_date = "2023-05"
        mock_obj.get_complete_publication_date.return_value = "2023-05-15"
        self.assertEqual(self.pkg.pub_date, "2023-05-15")

    def test_get_raises_value_error_when_ppx_id_is_falsy(self):
        with self.assertRaises(ValueError):
            SPSPkg.get(None, pid_v3="v3-00001")
        with self.assertRaises(ValueError):
            SPSPkg.get(0, pid_v3="v3-00001")

    def test_get_method_single_object_via_ppx_id_fallback(self):
        # ppx_id informado mas sem correspondencia; como existe um SPSPkg
        # com ppx nulo, search_by_ppx_id retorna None e get() cai no
        # fallback por pid_v3
        other_ppx = PidProviderXML.objects.create(creator=self.user)
        found = SPSPkg.get(other_ppx.id, pid_v3="v3-00001")
        self.assertEqual(found, self.pkg)

    def test_get_method_does_not_exist(self):
        # ppx_id informado e sem nenhum SPSPkg com ppx nulo no banco:
        # search_by_ppx_id levanta DoesNotExist e get() propaga
        self.pkg.ppx = PidProviderXML.objects.create(creator=self.user)
        self.pkg.save()
        other_ppx = PidProviderXML.objects.create(creator=self.user)
        with self.assertRaises(SPSPkg.DoesNotExist):
            SPSPkg.get(other_ppx.id, pid_v3="non-existent")

    def test_get_method_multiple_objects_returned(self):
        # com ppx_id fornecido e sem correspondencia direta, mas com
        # multiplos SPSPkg de ppx nulo, search_by_ppx_id retorna o mais
        # recente sem consultar pid_v3 - portanto MultipleObjectsReturned
        # NAO e mais levantado neste cenario (ver teste abaixo para o
        # caminho que ainda levanta a excecao via search_by_identifiers)
        second = SPSPkg.objects.create(
            creator=self.user,
            sps_pkg_name="sps-12345-v1",
            pid_v3="v3-00001",
            pid_v2="v2-00001",
        )
        other_ppx = PidProviderXML.objects.create(creator=self.user)
        found = SPSPkg.get(other_ppx.id, pid_v3="v3-00001")
        self.assertEqual(found, second)

    def test_get_method_multiple_objects_returned_via_identifiers(self):
        # forcando o fallback a bater em search_by_identifiers com
        # identificacao divergente entre os registros
        SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="sps-12345-v1",
            pid_v3="v3-00001", pid_v2="v2-diff",
        )
        SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="sps-12345-v1-x",
            pid_v3="v3-00001", pid_v2="v2-diff-3",
        )
        with self.assertRaises(SPSPkgMultipleObjectReturnedException):
            SPSPkg.get(123, pid_v3="v3-00001", sps_pkg_name="sps-12345-v1-x")


class SPSPkgSearchByPpxIdTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="searchppxuser", password="pass"
        )
        self.registered_ppx = PidProviderXML.objects.create(creator=self.user)
        self.pkg_with_ppx = SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="pkg-with-ppx",
            pid_v3="v3-ppx", ppx=self.registered_ppx,
        )

    def test_returns_single_match(self):
        found = SPSPkg.search_by_ppx_id(self.registered_ppx.id)
        self.assertEqual(found, self.pkg_with_ppx)

    def test_returns_most_recent_on_multiple_matches(self):
        newer = SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="pkg-with-ppx-2",
            pid_v3="v3-ppx-2", ppx=self.registered_ppx,
        )
        found = SPSPkg.search_by_ppx_id(self.registered_ppx.id)
        self.assertEqual(found, newer)

    def test_raises_does_not_exist_when_sps_pkg_and_pid_provider_are_not_related(self):
        SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="pkg-null-ppx", pid_v3="v3-null",
        )
        other_ppx = PidProviderXML.objects.create(creator=self.user)
        with self.assertRaises(SPSPkg.DoesNotExist):
            SPSPkg.search_by_ppx_id(other_ppx.id)

    def test_raises_does_not_exist_when_no_match_and_no_null_ppx_items(self):
        SPSPkg.objects.exclude(id=self.pkg_with_ppx.id).delete()
        other_ppx = PidProviderXML.objects.create(creator=self.user)
        with self.assertRaises(SPSPkg.DoesNotExist):
            SPSPkg.search_by_ppx_id(other_ppx.id)


class SPSPkgSearchByIdentifiersTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="searchiduser", password="pass"
        )
        self.pkg = SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="sps-1", pid_v3="v3-1", pid_v2="v2-1",
        )

    def test_raises_value_error_without_any_identifier(self):
        with self.assertRaises(ValueError):
            SPSPkg.search_by_identifiers()

    def test_returns_single_match(self):
        found = SPSPkg.search_by_identifiers(pid_v3="v3-1")
        self.assertEqual(found, self.pkg)

    def test_raises_does_not_exist_when_no_match(self):
        with self.assertRaises(SPSPkg.DoesNotExist):
            SPSPkg.search_by_identifiers(pid_v3="nonexistent")

    def test_multiple_matches_with_same_identification_returns_most_recent(self):
        newer = SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="sps-1-dup",
            pid_v3="v3-1", pid_v2="v2-1",
        )
        found = SPSPkg.search_by_identifiers(pid_v3="v3-1", pid_v2="v2-1")
        self.assertEqual(found, newer)

    def test_multiple_matches_with_different_identification_raises_custom_exception(self):
        SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="sps-2", pid_v3="v3-2", pid_v2="v2-1",
        )
        with self.assertRaises(SPSPkgMultipleObjectReturnedException):
            SPSPkg.search_by_identifiers(pid_v3="v3-1", pid_v2="v2-1")


class SPSPkgGetTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="getuser", password="pass"
        )
        self.registered_ppx = PidProviderXML.objects.create(creator=self.user)

    def test_get_raises_value_error_without_ppx_id(self):
        with self.assertRaises(ValueError):
            SPSPkg.get(None, pid_v3="does-not-matter")
        with self.assertRaises(ValueError):
            SPSPkg.get("")

    def test_get_finds_by_ppx_id_first(self):
        pkg = SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="pkg-a", pid_v3="v3-a",
            ppx=self.registered_ppx,
        )
        found = SPSPkg.get(self.registered_ppx.id, pid_v3="does-not-matter")
        self.assertEqual(found, pkg)

    def test_get_falls_back_to_identifiers_when_ppx_id_not_found_but_null_items_exist(self):
        pkg = SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="pkg-b", pid_v3="v3-b",
        )
        other_ppx = PidProviderXML.objects.create(creator=self.user)
        found = SPSPkg.get(other_ppx.id, pid_v3="v3-b")
        self.assertEqual(found, pkg)

    def test_get_raises_does_not_exist_when_ppx_id_given_and_no_null_items_exist(self):
        SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="pkg-c", pid_v3="v3-c",
            ppx=self.registered_ppx,
        )
        other_ppx = PidProviderXML.objects.create(creator=self.user)
        with self.assertRaises(SPSPkg.DoesNotExist):
            SPSPkg.get(other_ppx.id, pid_v3="v3-c")


class SPSPkgAddPpxTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser", password="pass"
        )
        self.registered_ppx = PidProviderXML.objects.create(creator=self.user)
        self.sps_pkg = SPSPkg.objects.create(
            sps_pkg_name="1234-5678-2024-01-01-0001",
            pid_v2="S1234-56782024000100001",
            file="fake/path.zip",
            creator=self.user,
        )

    @patch("package.models.pid_provider_app.is_registered_xml_zip")
    def test_add_ppx_success_saves_by_default(self, mock_is_registered):
        ppx_id = self.registered_ppx.id
        mock_is_registered.return_value = ({"ppx_id": ppx_id},)

        response = self.sps_pkg.add_ppx(self.user, save=True)

        self.assertIsNone(response)
        self.assertEqual(self.sps_pkg.ppx_id, ppx_id)
        self.sps_pkg.refresh_from_db()
        self.assertEqual(self.sps_pkg.ppx_id, ppx_id)

    @patch("package.models.pid_provider_app.is_registered_xml_zip")
    def test_add_ppx_with_save_false_does_not_persist(self, mock_is_registered):
        ppx_id = self.registered_ppx.id
        mock_is_registered.return_value = ({"ppx_id": ppx_id},)

        response = self.sps_pkg.add_ppx(self.user, save=False)

        self.assertIsNone(response)
        self.assertEqual(self.sps_pkg.ppx_id, ppx_id)

        self.sps_pkg.refresh_from_db()
        self.assertIsNone(self.sps_pkg.ppx_id)

    @patch("package.models.pid_provider_app.is_registered_xml_zip")
    def test_add_ppx_failure_returns_registered_and_does_not_set_ppx(
        self, mock_is_registered
    ):
        mock_is_registered.return_value = ({"error": "xml not found"},)

        response = self.sps_pkg.add_ppx(self.user, save=False)

        self.assertEqual(response, {"error": "xml not found"})
        self.assertIsNone(self.sps_pkg.ppx_id)


class SPSPkgCompletePpxTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser2", password="pass"
        )
        self.registered_ppx = PidProviderXML.objects.create(creator=self.user)
        self.pkg_ok = SPSPkg.objects.create(
            sps_pkg_name="pkg-ok", pid_v2="v2-ok",
            file="fake/ok.zip", creator=self.user,
        )
        self.pkg_fail = SPSPkg.objects.create(
            sps_pkg_name="pkg-fail", pid_v2="v2-fail",
            file="fake/fail.zip", creator=self.user,
        )
        self.pkg_error = SPSPkg.objects.create(
            sps_pkg_name="pkg-error", pid_v2="v2-error",
            file="fake/error.zip", creator=self.user,
        )

    @patch.object(SPSPkg, "add_ppx", autospec=True)
    def test_complete_ppx_calls_add_ppx_with_save_false(self, mock_add_ppx):
        def fake_add_ppx(self_pkg, user, save=False):
            self.assertFalse(save)
            if self_pkg.sps_pkg_name == "pkg-ok":
                self_pkg.ppx_id = self.registered_ppx.id
                return None
            if self_pkg.sps_pkg_name == "pkg-error":
                raise Exception("boom")
            return {"error": "not registered"}

        mock_add_ppx.side_effect = fake_add_ppx

        response = SPSPkg.complete_ppx(user=self.user, pkg_name_substr="pkg-")

        self.assertIn("pkg-ok", response["success"])
        self.assertEqual(len(response["failures"]), 2)

        failure_names = [f["name"] for f in response["failures"]]
        self.assertIn("pkg-fail", failure_names)
        self.assertIn("pkg-error", failure_names)

        self.pkg_ok.refresh_from_db()
        self.assertEqual(self.pkg_ok.ppx_id, self.registered_ppx.id)

    @patch.object(SPSPkg, "add_ppx", autospec=True)
    def test_complete_ppx_traceback_included_on_exception(self, mock_add_ppx):
        mock_add_ppx.side_effect = Exception("boom")

        response = SPSPkg.complete_ppx(
            user=self.user, sps_pkg_id_list=[self.pkg_error.id]
        )

        self.assertEqual(len(response["failures"]), 1)
        failure = response["failures"][0]
        self.assertEqual(failure["name"], "pkg-error")
        self.assertIn("boom", failure["response"])

    def test_complete_ppx_filters_by_sps_pkg_id_list(self):
        with patch.object(SPSPkg, "add_ppx", autospec=True) as mock_add_ppx:
            mock_add_ppx.return_value = None
            SPSPkg.complete_ppx(user=self.user, sps_pkg_id_list=[self.pkg_ok.id])

        called_pks = [call.args[0].id for call in mock_add_ppx.call_args_list]
        self.assertEqual(called_pks, [self.pkg_ok.id])

    def test_complete_ppx_filters_by_pkg_name_substr(self):
        with patch.object(SPSPkg, "add_ppx", autospec=True) as mock_add_ppx:
            mock_add_ppx.return_value = None
            SPSPkg.complete_ppx(user=self.user, pkg_name_substr="fail")

        called_names = [call.args[0].sps_pkg_name for call in mock_add_ppx.call_args_list]
        self.assertEqual(called_names, ["pkg-fail"])

    def test_complete_ppx_skips_items_that_already_have_ppx(self):
        registered_ppx = PidProviderXML.objects.create(creator=self.user)
        pkg_with_ppx = SPSPkg.objects.create(
            sps_pkg_name="pkg-has-ppx", pid_v2="v2-has",
            file="fake/has.zip", creator=self.user, ppx=registered_ppx,
        )

        with patch.object(SPSPkg, "add_ppx", autospec=True) as mock_add_ppx:
            mock_add_ppx.return_value = None
            SPSPkg.complete_ppx(user=self.user, pkg_name_substr="pkg-")

        called_ids = [call.args[0].id for call in mock_add_ppx.call_args_list]
        self.assertNotIn(pkg_with_ppx.id, called_ids)


# ============================================================
# SPSPkg.fix_sps_pkg_names()
# ============================================================


class SPSPkgFixSpsPkgNamesTestCase(TestCase):
    """Testes para SPSPkg.fix_sps_pkg_names() (correção em lote).

    O método consulta os SPSPkg candidatos (por nome na lista, ou sem nome
    mas com o pid_v2/pid_v3 informado), chama fix_sps_pkg_name() (sem save)
    em cada um, e persiste via bulk_update apenas os que de fato mudaram.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="fixnamesuser", password="pass"
        )
        self.pkg_changed = SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="old-name",
            pid_v3="v3-1", pid_v2="v2-1",
        )
        self.pkg_unchanged = SPSPkg.objects.create(
            creator=self.user, sps_pkg_name="same-name",
            pid_v3="v3-2", pid_v2="v2-2",
        )

    def test_updates_only_items_whose_name_actually_changes(self):
        def fake_fix(self_pkg):
            if self_pkg.pid_v3 == "v3-1":
                self_pkg.sps_pkg_name = "new-name"
                return True
            return False

        with patch.object(SPSPkg, "fix_sps_pkg_name", autospec=True) as mock_fix:
            mock_fix.side_effect = fake_fix

            total = SPSPkg.fix_sps_pkg_names(
                pid_v3="v3-1",
                pid_v2="v2-1",
                pkg_name_list=["old-name", "same-name"],
            )

        self.assertEqual(total, 1)
        self.pkg_changed.refresh_from_db()
        self.pkg_unchanged.refresh_from_db()
        self.assertEqual(self.pkg_changed.sps_pkg_name, "new-name")
        self.assertEqual(self.pkg_unchanged.sps_pkg_name, "same-name")

    def test_returns_zero_and_skips_bulk_update_when_nothing_changes(self):
        with patch.object(
            SPSPkg, "fix_sps_pkg_name", autospec=True, return_value=False
        ), patch.object(SPSPkg.objects, "bulk_update") as mock_bulk_update:
            total = SPSPkg.fix_sps_pkg_names(
                pid_v3="v3-1",
                pid_v2="v2-1",
                pkg_name_list=["old-name", "same-name"],
            )

        self.assertEqual(total, 0)
        mock_bulk_update.assert_not_called()


# ============================================================
# SPSPkg.exclude_invalid_records() (wrapper)
# ============================================================


class SPSPkgExcludeInvalidRecordsTestCase(unittest.TestCase):
    """Testes para o wrapper exclude_invalid_records()."""

    def test_wrapper_catches_exceptions(self):
        with patch.object(
            SPSPkg, "_exclude_invalid_records", side_effect=Exception("boom")
        ):
            result = SPSPkg.exclude_invalid_records(
                Mock(), "0034-777220210006", True, True
            )
        self.assertIn("error", result)
        self.assertEqual(result["error"], "boom")
        self.assertIn("traceback", result)

    def test_wrapper_returns_inner_result_on_success(self):
        expected = {"total_deleted_items": 0}
        with patch.object(
            SPSPkg, "_exclude_invalid_records", return_value=expected
        ):
            result = SPSPkg.exclude_invalid_records(
                Mock(), "0034-777220210006", True, True
            )
        self.assertEqual(result, expected)


# ============================================================
# SPSPkg._exclude_invalid_records()
# ============================================================


class SPSPkgExcludeInvalidRecordsInternalTestCase(unittest.TestCase):
    """Testes para SPSPkg._exclude_invalid_records().

    Fluxo atual:
    1. `cls.objects.filter(pid_v2__startswith=f"S{issue_pid}")` -> queryset base.
    2. `sps_pkgs.filter(ppx_id__isnull=True)` -> SPSPkg sem ppx, removidos via
       delete_related_items; se algo foi deletado, sps_pkgs é reconsultado.
    3. `sps_pkgs.values("ppx_id").annotate(total=Count("id")).filter(total__gt=1)`
       -> valores de ppx_id duplicados.
    4. Para cada valor duplicado: mantém o primeiro de
       `filter(ppx_id=value).order_by("-updated")` e remove os demais via
       delete_related_items.
    """

    @patch.object(SPSPkg, "delete_related_items")
    @patch("package.models.SPSPkg.objects")
    def test_no_missing_ppx_and_no_duplicates(self, mock_objects, mock_delete_related):
        sps_pkgs_qs = MagicMock()
        sps_pkgs_qs.count.return_value = 5

        empty_qs = MagicMock()
        empty_qs.__bool__.return_value = False
        sps_pkgs_qs.filter.return_value = empty_qs
        sps_pkgs_qs.values.return_value.annotate.return_value.filter.return_value.values_list.return_value = []

        mock_objects.filter.return_value = sps_pkgs_qs

        result = SPSPkg._exclude_invalid_records(
            Mock(), "0034-777220210006",
            delete_sps_pkg_which_ppx_is_missing=True,
            delete_sps_pkg_which_is_duplicated=True,
        )

        self.assertEqual(result["total_sps_pkgs"], 5)
        self.assertEqual(result["total_deleted_items"], 0)
        self.assertEqual(result["exceptions"], [])
        self.assertEqual(result["duplicated_items"], [])
        self.assertNotIn("total_delete_sps_pkg_which_ppx_is_missing", result)
        mock_delete_related.assert_not_called()

    @patch.object(SPSPkg, "delete_related_items", return_value=(3, {}))
    @patch("package.models.SPSPkg.objects")
    def test_deletes_sps_pkg_missing_ppx_and_requeries(
        self, mock_objects, mock_delete_related
    ):
        first_qs = MagicMock()
        first_qs.count.return_value = 5
        to_delete_qs = MagicMock()
        to_delete_qs.__bool__.return_value = True
        first_qs.filter.return_value = to_delete_qs

        second_qs = MagicMock()
        second_qs.count.return_value = 2
        second_qs.values.return_value.annotate.return_value.filter.return_value.values_list.return_value = []

        mock_objects.filter.side_effect = [first_qs, second_qs]

        result = SPSPkg._exclude_invalid_records(
            Mock(), "0034-777220210006",
            delete_sps_pkg_which_ppx_is_missing=True,
            delete_sps_pkg_which_is_duplicated=False,
        )

        self.assertEqual(mock_objects.filter.call_count, 2)
        mock_delete_related.assert_called_once_with(to_delete_qs)
        self.assertEqual(result["total_sps_pkgs"], 5)
        self.assertEqual(result["total_delete_sps_pkg_which_ppx_is_missing"], 3)
        self.assertEqual(result["total_deleted_items"], 3)

    @patch.object(SPSPkg, "delete_related_items", side_effect=Exception("db error"))
    @patch("package.models.SPSPkg.objects")
    def test_captures_exception_when_deleting_missing_ppx(
        self, mock_objects, mock_delete_related
    ):
        sps_pkgs_qs = MagicMock()
        sps_pkgs_qs.count.return_value = 5
        to_delete_qs = MagicMock()
        to_delete_qs.__bool__.return_value = True
        sps_pkgs_qs.filter.return_value = to_delete_qs
        sps_pkgs_qs.values.return_value.annotate.return_value.filter.return_value.values_list.return_value = []

        mock_objects.filter.return_value = sps_pkgs_qs

        result = SPSPkg._exclude_invalid_records(
            Mock(), "0034-777220210006",
            delete_sps_pkg_which_ppx_is_missing=True,
            delete_sps_pkg_which_is_duplicated=True,  # necessário p/ "exceptions" existir no dict
        )

        self.assertEqual(len(result["exceptions"]), 1)
        self.assertEqual(
            result["exceptions"][0]["action"], "deleting due to missing ppx"
        )
        self.assertEqual(result["total_deleted_items"], 0)
        self.assertNotIn("total_delete_sps_pkg_which_ppx_is_missing", result)

    @patch.object(SPSPkg, "delete_related_items", return_value=(2, {}))
    @patch("package.models.SPSPkg.objects")
    def test_removes_duplicated_ppx_keeping_the_chosen_one(
        self, mock_objects, mock_delete_related
    ):
        sps_pkgs_qs = MagicMock()
        sps_pkgs_qs.count.return_value = 3

        no_missing_qs = MagicMock()
        no_missing_qs.__bool__.return_value = False

        duplicados_qs = MagicMock()
        duplicados_qs.order_by.return_value = duplicados_qs
        duplicados_qs.count.return_value = 3
        keep = Mock()
        keep.id = 10
        duplicados_qs.first.return_value = keep
        remover_qs = MagicMock()
        duplicados_qs.exclude.return_value = remover_qs

        def filter_side_effect(**kwargs):
            if "ppx_id__isnull" in kwargs:
                return no_missing_qs
            if "ppx_id" in kwargs:
                return duplicados_qs
            raise AssertionError(f"filter inesperado: {kwargs}")

        sps_pkgs_qs.filter.side_effect = filter_side_effect
        sps_pkgs_qs.values.return_value.annotate.return_value.filter.return_value.values_list.return_value = [99]

        mock_objects.filter.return_value = sps_pkgs_qs

        result = SPSPkg._exclude_invalid_records(
            Mock(), "0034-777220210006",
            delete_sps_pkg_which_ppx_is_missing=True,
            delete_sps_pkg_which_is_duplicated=True,
        )

        duplicados_qs.exclude.assert_called_once_with(id=10)
        mock_delete_related.assert_called_once_with(remover_qs)

        self.assertEqual(len(result["duplicated_items"]), 1)
        item = result["duplicated_items"][0]
        self.assertEqual(item["value"], 99)
        self.assertEqual(item["total"], 3)
        self.assertEqual(item["total_deleted"], 2)
        self.assertEqual(result["total_deleted_items"], 2)
        self.assertEqual(result["exceptions"], [])

    @patch.object(SPSPkg, "delete_related_items")
    @patch("package.models.SPSPkg.objects")
    def test_captures_exception_during_duplicate_removal(
        self, mock_objects, mock_delete_related
    ):
        sps_pkgs_qs = MagicMock()
        sps_pkgs_qs.count.return_value = 3

        no_missing_qs = MagicMock()
        no_missing_qs.__bool__.return_value = False

        def filter_side_effect(**kwargs):
            if "ppx_id__isnull" in kwargs:
                return no_missing_qs
            raise Exception("boom")

        sps_pkgs_qs.filter.side_effect = filter_side_effect
        sps_pkgs_qs.values.return_value.annotate.return_value.filter.return_value.values_list.return_value = [99]

        mock_objects.filter.return_value = sps_pkgs_qs

        result = SPSPkg._exclude_invalid_records(
            Mock(), "0034-777220210006",
            delete_sps_pkg_which_ppx_is_missing=True,
            delete_sps_pkg_which_is_duplicated=True,
        )

        self.assertEqual(len(result["exceptions"]), 1)
        self.assertEqual(result["exceptions"][0]["action"], "removing duplicity")
        self.assertEqual(result["exceptions"][0]["item"], 99)
        mock_delete_related.assert_not_called()
        self.assertEqual(result["total_deleted_items"], 0)


class SPSPkgDeleteRelatedItemsTestCase(unittest.TestCase):
    """Testes para SPSPkg.delete_related_items()."""

    @patch("package.models.SPSPkgComponent")
    def test_deletes_components_and_returns_queryset_delete_result(
        self, mock_component
    ):
        mock_qs = MagicMock()
        mock_qs.delete.return_value = (3, {"package.SPSPkg": 3})

        result = SPSPkg.delete_related_items(mock_qs)

        mock_component.objects.filter.assert_called_once_with(sps_pkg__in=mock_qs)
        mock_component.objects.filter.return_value.delete.assert_called_once()
        mock_qs.delete.assert_called_once()
        self.assertEqual(result, (3, {"package.SPSPkg": 3}))


if __name__ == "__main__":
    unittest.main()
