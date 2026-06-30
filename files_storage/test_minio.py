# coding: utf-8
"""
Testes de files_storage.minio alinhados ao CONTRATO REAL de MinioStorage:

    MinioStorage(
        minio_host, minio_access_key, minio_secret_key,
        bucket, object_name_prefix, public_url, location,
        minio_secure=True, minio_http_client=None,
    )

Observações de comportamento (verificadas no código sob teste):
- get_uri: com public_url -> f"{public_url}/{object_name}" (object_name CRU,
  sem object_name_prefix). Sem public_url -> presigned, aplicando
  get_full_object_name(object_name) e removendo a query string.
- fput: em S3Error com code == "NoSuchBucket" -> cria bucket, seta policy e
  faz RETRY recursivo. Em qualquer outro S3Error -> propaga o próprio S3Error
  (NÃO converte em MinioStorageFPutError).
- get_full_object_name: prefixa object_name_prefix quando presente.
"""
import json
from unittest.mock import patch

from django.test import TestCase
from minio.error import S3Error

from files_storage.minio import (
    MinioStorage,
    MinioStorageFgetError,
    MinioStorageFPutContentError,
    MinioStorageGetUriError,
)


def make_s3_error(code):
    """
    Instância de S3Error via __init__ oficial. O objeto é "frozen" após init
    e `code` é uma property sem setter, então não dá para setar atributos
    manualmente — usa-se o construtor. `response` pode ser qualquer objeto,
    pois o código sob teste só consulta `.code`.
    """
    return S3Error(
        response=None,
        code=code,
        message=code,
        resource="resource",
        request_id="request_id",
        host_id="host_id",
    )


class MinioStorageTest(TestCase):
    def setUp(self):
        # object_name_prefix simula o prefixo de gravação (ex.: nome do bucket
        # lógico dentro do host_root_dir). public_url é a base de leitura.
        self.minio_storage = MinioStorage(
            minio_host="localhost",
            minio_access_key="minio_access_key",
            minio_secret_key="minio_secret_key",
            bucket="instance_name",
            object_name_prefix="app_name",
            public_url="https://minio.scielo.br/app_name",
            location="sa-east-1",
            minio_secure=True,
            minio_http_client=None,
        )

    # ------------------------------------------------------------------ client

    @patch("files_storage.minio.Minio")
    def test__client_is_built_with_expected_args(self, mock_minio):
        _ = self.minio_storage._client
        mock_minio.assert_called_with(
            "localhost",
            access_key="minio_access_key",
            secret_key="minio_secret_key",
            secure=True,
            http_client=None,
        )

    @patch("files_storage.minio.Minio")
    def test__client_is_cached(self, mock_minio):
        first = self.minio_storage._client
        second = self.minio_storage._client
        self.assertIs(first, second)
        mock_minio.assert_called_once()

    # ------------------------------------------------------------- bucket setup

    @patch("files_storage.minio.Minio.make_bucket")
    def test__create_bucket(self, mock_make_bucket):
        self.minio_storage.location = "us-east-1"
        self.minio_storage._create_bucket()
        mock_make_bucket.assert_called_with(
            "instance_name",
            location="us-east-1",
        )

    @patch("files_storage.minio.Minio.set_bucket_policy")
    def test__set_bucket_policy(self, mock_set_bucket_policy):
        self.minio_storage._set_bucket_policy()
        mock_set_bucket_policy.assert_called_with(
            "instance_name",
            json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                            "Resource": ["arn:aws:s3:::instance_name"],
                        },
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": ["arn:aws:s3:::instance_name/*"],
                        },
                    ],
                }
            ),
        )

    # ------------------------------------------------------ get_full_object_name

    def test_get_full_object_name_with_prefix(self):
        self.assertEqual(
            "app_name/subdir/filename.xml",
            self.minio_storage.get_full_object_name("subdir/filename.xml"),
        )

    def test_get_full_object_name_without_prefix(self):
        self.minio_storage.object_name_prefix = ""
        self.assertEqual(
            "subdir/filename.xml",
            self.minio_storage.get_full_object_name("subdir/filename.xml"),
        )

    # ----------------------------------------------------------------- get_uri

    @patch("files_storage.minio.Minio.presigned_get_object")
    def test_get_uri_uses_public_url(self, mock_presigned_get_object):
        # Com public_url: concatena object_name CRU; presigned não é chamado e
        # object_name_prefix NÃO é reaplicado (a base pública já o embute).
        uri = self.minio_storage.get_uri("filename.xml")
        self.assertEqual("https://minio.scielo.br/app_name/filename.xml", uri)
        mock_presigned_get_object.assert_not_called()

    @patch("files_storage.minio.Minio.presigned_get_object")
    def test_get_uri_presigned_applies_prefix_and_strips_query(
        self, mock_presigned_get_object
    ):
        # Sem public_url: cai no presigned, aplica object_name_prefix e remove
        # a query string assinada.
        storage = MinioStorage(
            minio_host="localhost",
            minio_access_key="ak",
            minio_secret_key="sk",
            bucket="instance_name",
            object_name_prefix="app_name",
            public_url=None,
            location="sa-east-1",
        )
        mock_presigned_get_object.return_value = (
            "https://localhost/instance_name/app_name/filename.xml?X-Amz-Signature=abc"
        )
        uri = storage.get_uri("filename.xml")
        mock_presigned_get_object.assert_called_with(
            "instance_name",
            "app_name/filename.xml",
        )
        self.assertEqual(
            "https://localhost/instance_name/app_name/filename.xml", uri
        )

    @patch(
        "files_storage.minio.Minio.presigned_get_object",
        side_effect=Exception("boom"),
    )
    def test_get_uri_raises(self, mock_presigned_get_object):
        storage = MinioStorage(
            minio_host="localhost",
            minio_access_key="ak",
            minio_secret_key="sk",
            bucket="instance_name",
            object_name_prefix="app_name",
            public_url=None,
            location="sa-east-1",
        )
        with self.assertRaises(MinioStorageGetUriError):
            storage.get_uri("filename.xml")

    # -------------------------------------------------------------------- fput

    @patch("files_storage.minio.MinioStorage.get_uri")
    @patch("files_storage.minio.Minio.fput_object")
    def test_fput(self, mock_client_fput_object, mock_get_uri):
        # Grava sob object_name_prefix; get_uri recebe o object_name ORIGINAL.
        mock_get_uri.return_value = "https://minio.scielo.br/app_name/filename.xml"
        uri = self.minio_storage.fput(
            "/root/folder1/folder2/filename.xml",
            "subdir1/subdir2/filename.xml",
            mimetype="mimetype_informado",
        )
        mock_client_fput_object.assert_called_with(
            "instance_name",
            object_name="app_name/subdir1/subdir2/filename.xml",
            file_path="/root/folder1/folder2/filename.xml",
            content_type="mimetype_informado",
        )
        mock_get_uri.assert_called_with("subdir1/subdir2/filename.xml")
        self.assertEqual("https://minio.scielo.br/app_name/filename.xml", uri)

    @patch("files_storage.minio.MinioStorage.get_uri")
    @patch("files_storage.minio.get_mimetype")
    @patch("files_storage.minio.Minio.fput_object")
    def test_fput_detects_mimetype(
        self, mock_client_fput_object, mock_get_mimetype, mock_get_uri
    ):
        mock_get_mimetype.return_value = "mimetype_identificado"
        self.minio_storage.fput(
            "/root/folder1/folder2/filename.xml",
            "subdir1/subdir2/filename.xml",
            mimetype=None,
        )
        mock_get_mimetype.assert_called_with("/root/folder1/folder2/filename.xml")
        mock_client_fput_object.assert_called_with(
            "instance_name",
            object_name="app_name/subdir1/subdir2/filename.xml",
            file_path="/root/folder1/folder2/filename.xml",
            content_type="mimetype_identificado",
        )

    @patch("files_storage.minio.MinioStorage._set_bucket_policy")
    @patch("files_storage.minio.MinioStorage._create_bucket")
    @patch("files_storage.minio.MinioStorage.get_uri")
    @patch("files_storage.minio.Minio.fput_object")
    def test_fput_no_such_bucket_creates_and_retries(
        self,
        mock_client_fput_object,
        mock_get_uri,
        mock_create_bucket,
        mock_set_bucket_policy,
    ):
        # Comportamento real: NoSuchBucket -> cria bucket, seta policy e faz
        # RETRY recursivo. 1ª chamada de fput_object falha; 2ª (retry) ok.
        mock_client_fput_object.side_effect = [make_s3_error("NoSuchBucket"), None]
        mock_get_uri.return_value = "URI"

        uri = self.minio_storage.fput(
            "/root/folder1/folder2/filename.xml",
            "subdir1/subdir2/filename.xml",
            mimetype="mimetype_informado",
        )

        self.assertEqual("URI", uri)
        mock_create_bucket.assert_called_once_with()
        mock_set_bucket_policy.assert_called_once_with()
        self.assertEqual(mock_client_fput_object.call_count, 2)

    @patch("files_storage.minio.MinioStorage._set_bucket_policy")
    @patch("files_storage.minio.MinioStorage._create_bucket")
    @patch("files_storage.minio.Minio.fput_object")
    def test_fput_other_s3error_is_propagated(
        self, mock_client_fput_object, mock_create_bucket, mock_set_bucket_policy
    ):
        # S3Error diferente de NoSuchBucket é re-levantado como S3Error
        # (o código faz `raise e`, sem converter em MinioStorageFPutError) e
        # não dispara criação de bucket.
        mock_client_fput_object.side_effect = make_s3_error("AccessDenied")
        with self.assertRaises(S3Error):
            self.minio_storage.fput(
                "/root/filename.xml",
                "subdir/filename.xml",
                mimetype="mt",
            )
        mock_create_bucket.assert_not_called()
        mock_set_bucket_policy.assert_not_called()

    # ------------------------------------------------------------ fput_content

    @patch("files_storage.minio.MinioStorage.fput")
    def test_fput_content_returns_uri(self, mock_fput):
        mock_fput.return_value = "uri"
        uri = self.minio_storage.fput_content(
            content=b"<article/>",
            mimetype="text/xml",
            object_name="object_name.xml",
        )
        self.assertEqual("uri", uri)

    @patch("files_storage.minio.MinioStorage.fput")
    def test_fput_content_calls_fput(self, mock_fput):
        mock_fput.return_value = "uri"
        self.minio_storage.fput_content(
            content=b"<article/>",
            mimetype="text/xml",
            object_name="object_name.xml",
        )
        args, _ = mock_fput.call_args
        self.assertTrue(args[0].endswith("object_name.xml"))  # file_path temp
        self.assertEqual("object_name.xml", args[1])           # object_name
        self.assertEqual("text/xml", args[2])                  # mimetype

    @patch(
        "files_storage.minio.MinioStorage.fput", side_effect=Exception("boom")
    )
    def test_fput_content_raises(self, mock_fput):
        with self.assertRaises(MinioStorageFPutContentError):
            self.minio_storage.fput_content(
                content=b"<article/>",
                mimetype="text/xml",
                object_name="object_name.xml",
            )

    # ------------------------------------------------------------------- remove

    @patch("files_storage.minio.Minio.remove_object")
    def test_remove(self, mock_remove):
        self.minio_storage.remove("filename.xml")
        mock_remove.assert_called_with(
            "instance_name",
            "app_name/filename.xml",
        )

    # --------------------------------------------------------------------- fget

    @patch("files_storage.minio.Minio.fget_object")
    def test_fget(self, mock_fget):
        path = self.minio_storage.fget("filename.xml", "/tmp/dest.xml")
        mock_fget.assert_called_with(
            "instance_name",
            "app_name/filename.xml",
            "/tmp/dest.xml",
        )
        self.assertEqual("/tmp/dest.xml", path)

    @patch("files_storage.minio._create_tmp_file")
    @patch("files_storage.minio.Minio.fget_object")
    def test_fget_creates_tmp_file(self, mock_fget, mock_create_tmp_file):
        mock_create_tmp_file.return_value = "/tmp/auto.xml"
        path = self.minio_storage.fget("filename.xml")
        mock_create_tmp_file.assert_called_once_with()
        mock_fget.assert_called_with(
            "instance_name",
            "app_name/filename.xml",
            "/tmp/auto.xml",
        )
        self.assertEqual("/tmp/auto.xml", path)

    @patch("files_storage.minio.Minio.fget_object", side_effect=Exception("boom"))
    def test_fget_raises(self, mock_fget):
        with self.assertRaises(MinioStorageFgetError):
            self.minio_storage.fget("filename.xml", "/tmp/dest.xml")