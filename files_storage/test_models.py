# coding: utf-8
"""
Testes de files_storage.models.

Cobre MinioConfiguration (get_or_create, get, get_files_storage e as
properties object_name_prefix / public_url) e FileLocation (get_or_create).

Notas:
- creator (CommonControlField), access_key e secret_key são NOT NULL; os testes
  sempre fornecem user/creator e credenciais ao persistir.
- get_files_storage instancia MinioStorage com o contrato real de
  files_storage.minio:
      bucket             <- obj.host_root_dir or obj.bucket
      object_name_prefix <- obj.object_name_prefix
      public_url         <- obj.public_url
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from files_storage import exceptions
from files_storage.models import FileLocation, MinioConfiguration

User = get_user_model()


class MinioConfigurationGetOrCreateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tester", password="x")

    def test_creates_when_absent(self):
        obj = MinioConfiguration.get_or_create(
            name="website",
            host="s3.wasabisys.com",
            access_key="ak",
            secret_key="sk",
            secure=True,
            bucket="upload",
            host_root_dir="scielo",
            public_base_url="https://minio.scielo.br/scielo",
            location="sa-east-1",
            user=self.user,
        )
        self.assertIsNotNone(obj.pk)
        self.assertEqual("website", obj.name)
        self.assertEqual("s3.wasabisys.com", obj.host)
        self.assertEqual("upload", obj.bucket)
        self.assertEqual("scielo", obj.host_root_dir)
        self.assertEqual("https://minio.scielo.br/scielo", obj.public_base_url)
        self.assertEqual("sa-east-1", obj.location)
        self.assertTrue(obj.secure)

    def test_returns_existing_without_creating(self):
        first = MinioConfiguration.get_or_create(
            name="website", host="h1", access_key="ak", secret_key="sk",
            secure=True, bucket="upload", user=self.user,
        )
        second = MinioConfiguration.get_or_create(
            name="website", host="h2", access_key="ak", secret_key="sk",
            secure=True, bucket="upload", user=self.user,
        )
        self.assertEqual(first.pk, second.pk)
        # Não atualiza os campos do existente; host permanece o original.
        self.assertEqual("h1", second.host)
        self.assertEqual(1, MinioConfiguration.objects.filter(name="website").count())


class MinioConfigurationGetTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tester", password="x")

    def test_get_returns_object(self):
        created = MinioConfiguration.get_or_create(
            name="website", host="h", access_key="ak", secret_key="sk",
            secure=True, bucket="upload", user=self.user,
        )
        self.assertEqual(created.pk, MinioConfiguration.get("website").pk)

    def test_get_returns_none_when_absent(self):
        self.assertIsNone(MinioConfiguration.get("inexistente"))


class MinioConfigurationPropertiesTest(TestCase):
    """Properties são puras (não tocam o banco) -> instâncias não salvas."""

    def test_object_name_prefix_with_host_root_dir(self):
        obj = MinioConfiguration(bucket="upload", host_root_dir="scielo")
        self.assertEqual("upload", obj.object_name_prefix)

    def test_object_name_prefix_without_host_root_dir(self):
        obj = MinioConfiguration(bucket="upload", host_root_dir=None)
        self.assertEqual("", obj.object_name_prefix)

    def test_public_url_uses_public_base_url_with_prefix(self):
        obj = MinioConfiguration(
            host="s3.host", bucket="upload", host_root_dir="scielo",
            public_base_url="https://minio.scielo.br", secure=True,
        )
        self.assertEqual("https://minio.scielo.br/upload", obj.public_url)

    def test_public_url_uses_public_base_url_without_prefix(self):
        obj = MinioConfiguration(
            host="s3.host", bucket="upload", host_root_dir=None,
            public_base_url="https://minio.scielo.br",
        )
        self.assertEqual("https://minio.scielo.br", obj.public_url)

    def test_public_url_falls_back_to_host_https(self):
        obj = MinioConfiguration(
            host="s3.host", bucket="upload", host_root_dir="scielo",
            public_base_url=None, secure=True,
        )
        self.assertEqual("https://s3.host/upload", obj.public_url)

    def test_public_url_falls_back_to_host_http_when_not_secure(self):
        obj = MinioConfiguration(
            host="s3.host", bucket="upload", host_root_dir=None,
            public_base_url=None, secure=False,
        )
        self.assertEqual("http://s3.host", obj.public_url)


class MinioConfigurationGetFilesStorageTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tester", password="x")

    @patch("files_storage.models.MinioStorage")
    def test_builds_storage_from_named_config(self, mock_storage):
        MinioConfiguration.get_or_create(
            name="website", host="s3.host", access_key="ak", secret_key="sk",
            secure=True, bucket="upload", host_root_dir="scielo",
            public_base_url="https://minio.scielo.br", location="sa-east-1",
            user=self.user,
        )
        MinioConfiguration.get_files_storage("website")

        mock_storage.assert_called_once_with(
            minio_host="s3.host",
            minio_access_key="ak",
            minio_secret_key="sk",
            bucket="scielo",  # host_root_dir tem precedência sobre bucket
            object_name_prefix="upload",
            public_url="https://minio.scielo.br/upload",
            location="sa-east-1",
            minio_secure=True,
            minio_http_client=None,
        )

    @patch("files_storage.models.MinioStorage")
    def test_bucket_falls_back_to_bucket_when_no_host_root_dir(self, mock_storage):
        MinioConfiguration.get_or_create(
            name="website", host="s3.host", access_key="ak", secret_key="sk",
            secure=False, bucket="upload", host_root_dir=None,
            public_base_url=None, location="sa-east-1", user=self.user,
        )
        MinioConfiguration.get_files_storage("website")

        _, kwargs = mock_storage.call_args
        self.assertEqual("upload", kwargs["bucket"])
        self.assertEqual("", kwargs["object_name_prefix"])
        self.assertEqual("http://s3.host", kwargs["public_url"])

    @patch("files_storage.models.MinioStorage")
    def test_falls_back_to_first_config_when_name_absent(self, mock_storage):
        MinioConfiguration.get_or_create(
            name="other", host="fallback.host", access_key="ak", secret_key="sk",
            secure=True, bucket="upload", user=self.user,
        )
        MinioConfiguration.get_files_storage("nao-existe")

        _, kwargs = mock_storage.call_args
        self.assertEqual("fallback.host", kwargs["minio_host"])

    @patch("files_storage.models.MinioStorage")
    def test_passes_http_client_through(self, mock_storage):
        MinioConfiguration.get_or_create(
            name="website", host="s3.host", access_key="ak", secret_key="sk",
            secure=True, bucket="upload", user=self.user,
        )
        sentinel = object()
        MinioConfiguration.get_files_storage("website", minio_http_client=sentinel)
        _, kwargs = mock_storage.call_args
        self.assertIs(sentinel, kwargs["minio_http_client"])


class FileLocationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tester", password="x")

    def test_creates_when_absent(self):
        obj = FileLocation.get_or_create(
            creator=self.user, uri="https://x/y.xml", basename="y.xml"
        )
        self.assertIsNotNone(obj.pk)
        self.assertEqual("https://x/y.xml", obj.uri)
        self.assertEqual("y.xml", obj.basename)

    def test_returns_existing_by_uri(self):
        first = FileLocation.get_or_create(creator=self.user, uri="https://x/y.xml")
        second = FileLocation.get_or_create(
            creator=self.user, uri="https://x/y.xml", basename="ignored.xml"
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(1, FileLocation.objects.filter(uri="https://x/y.xml").count())

    @patch("files_storage.models.FileLocation.objects")
    def test_wraps_unexpected_error(self, mock_objects):
        mock_objects.get.side_effect = ValueError("boom")
        with self.assertRaises(exceptions.MinioFileGetOrCreateError):
            FileLocation.get_or_create(creator=self.user, uri="https://x/y.xml")