# coding: utf-8
import unittest
from unittest.mock import MagicMock, patch, mock_open

# coding: utf-8
from mimetypes import types_map
from tempfile import NamedTemporaryFile, TemporaryDirectory

from minio import Minio
from minio.error import S3Error
from hashlib import sha1

from files_storage.minio import (
    get_mimetype,
    sha1,
    _create_tmp_file,
    MinioStorage,
    SHA1Error,
    MinioStorageGetUriError,
)


class TestStorageHelpers(unittest.TestCase):
    def test_get_mimetype_known_extension(self):
        # Testa extensão conhecida (.txt ou similar dependendo do mimetypes)
        path = "document.txt"
        mimetype = get_mimetype(path)
        self.assertEqual(mimetype, "text/plain")

    def test_get_mimetype_unknown_extension(self):
        # Testa extensão desconhecida que deve retornar o octet-stream padrão
        path = "file.unknownext123"
        mimetype = get_mimetype(path)
        self.assertEqual(mimetype, "application/octet-stream")

    @patch("builtins.open", new_callable=mock_open, read_data=b"hello world")
    @patch("hashlib.sha1")
    def test_sha1_success(self, mock_hashlib, mock_file):
        mock_sha1_instance = MagicMock()
        mock_sha1_instance.hexdigest.return_value = "2aaf14bc6066722ecd810657f68326d9c6e5e32d"
        mock_hashlib.return_value = mock_sha1_instance

        result = sha1("dummy_path")
        self.assertEqual(result, "2aaf14bc6066722ecd810657f68326d9c6e5e32d")
        mock_file.assert_called_once_with("dummy_path", "rb")

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_sha1_file_not_found(self, mock_file):
        with self.assertRaises(SHA1Error):
            sha1("non_existent_path")


class TestMinioStorage(unittest.TestCase):
    def setUp(self):
        self.storage = MinioStorage(
            minio_host="localhost:9000",
            minio_access_key="accesskey",
            minio_secret_key="secretkey",
            minio_bucket="test-bucket",
            minio_object_name_prefix="prefix",
            minio_public_url="http://localhost:9000/public",
            location="us-east-1",
            minio_secure=False,
        )

    def test_get_full_object_name_with_prefix(self):
        full_name = self.storage.get_full_object_name("folder/file.txt")
        self.assertEqual(full_name, "prefix/folder/file.txt")

    def test_get_full_object_name_without_prefix(self):
        self.storage.object_name_prefix = ""
        full_name = self.storage.get_full_object_name("folder/file.txt")
        self.assertEqual(full_name, "folder/file.txt")

    @patch("files_storage.minio.Minio")
    def test_get_uri_with_public_url(self, mock_minio_class):
        uri = self.storage.get_uri("file.txt")
        self.assertEqual(uri, "http://localhost:9000/public/file.txt")

    @patch("files_storage.minio.Minio")
    def test_get_uri_presigned(self, mock_minio_class):
        self.storage.public_url = None
        mock_client = MagicMock()
        mock_client.presigned_get_object.return_value = "http://localhost:9000/test-bucket/prefix/file.txt?signature=xyz"
        self.storage._client_instance = mock_client

        uri = self.storage.get_uri("file.txt")
        self.assertEqual(uri, "http://localhost:9000/test-bucket/prefix/file.txt")
        mock_client.presigned_get_object.assert_called_once_with(
            "test-bucket", "prefix/file.txt"
        )

    @patch("files_storage.minio.Minio")
    def test_get_uri_error(self, mock_minio_class):
        self.storage.public_url = None
        mock_client = MagicMock()
        mock_client.presigned_get_object.side_effect = Exception("Minio error")
        self.storage._client_instance = mock_client

        with self.assertRaises(MinioStorageGetUriError):
            self.storage.get_uri("file.txt")

    @patch("files_storage.minio.Minio")
    def test_fput_success(self, mock_minio_class):
        mock_client = MagicMock()
        self.storage._client_instance = mock_client

        with patch.object(self.storage, "get_uri", return_value="http://uri"):
            result = self.storage.fput("local_path.txt", "remote_path.txt")

        self.assertEqual(result, "http://uri")
        mock_client.fput_object.assert_called_once_with(
            "test-bucket",
            object_name="prefix/remote_path.txt",
            file_path="local_path.txt",
            content_type="text/plain",
        )

    @patch("files_storage.minio.Minio")
    def test_fput_no_such_bucket_retry(self, mock_minio_class):
        mock_client = MagicMock()
        # Simula erro de S3 com código NoSuchBucket na primeira chamada e sucesso na segunda
        s3_error = S3Error(
            code="NoSuchBucket",
            message="Bucket does not exist",
            resource="test-bucket",
            request_id="1",
            host_id="1",
            response=MagicMock(),
        )
        mock_client.fput_object.side_effect = [s3_error, None]
        self.storage._client_instance = mock_client

        with patch.object(self.storage, "_create_bucket") as mock_create_bucket, \
             patch.object(self.storage, "_set_bucket_policy") as mock_set_policy, \
             patch.object(self.storage, "get_uri", return_value="http://uri"):

            result = self.storage.fput("local_path.txt", "remote_path.txt")

            self.assertEqual(result, "http://uri")
            mock_create_bucket.assert_called_once()
            mock_set_policy.assert_called_once()
            self.assertEqual(mock_client.fput_object.call_count, 2)

    @patch("files_storage.minio.Minio")
    def test_fput_content_success(self, mock_minio_class):
        with patch.object(self.storage, "fput", return_value="http://uri") as mock_fput:
            result = self.storage.fput_content(b"content data", "text/plain", "file.txt")
            self.assertEqual(result, "http://uri")
            mock_fput.assert_called_once()

    @patch("files_storage.minio.Minio")
    def test_remove_object(self, mock_minio_class):
        mock_client = MagicMock()
        self.storage._client_instance = mock_client

        self.storage.remove("file.txt")
        mock_client.remove_object.assert_called_once_with(
            "test-bucket", "prefix/file.txt"
        )

    @patch("files_storage.minio.Minio")
    def test_fget_success(self, mock_minio_class):
        mock_client = MagicMock()
        self.storage._client_instance = mock_client

        path = self.storage.fget("file.txt", downloaded_file_path="/tmp/download.txt")
        self.assertEqual(path, "/tmp/download.txt")
        mock_client.fget_object.assert_called_once_with(
            "test-bucket", "prefix/file.txt", "/tmp/download.txt"
        )


class TestMinioStorageRealWorldScenarios(unittest.TestCase):

    def test_bucket_is_mandatory(self):
        """Garante que o bucket é obrigatório e inicializado corretamente."""
        storage = MinioStorage(
            minio_host="s3.wasabisys.com",
            minio_access_key="access",
            minio_secret_key="secret",
            minio_bucket="meu-bucket-producao",
            minio_object_name_prefix="meu-prefix",
            minio_public_url="https://meudominio.com/meu-bucket-producao",
            location="us-east-1",
        )
        self.assertEqual(storage.bucket, "meu-bucket-producao")

    @patch("files_storage.minio.Minio")
    def test_wasabi_scenario_with_app_prefix_and_public_url(self, mock_minio_class):
        """
        Cenário Real (Wasabi): 
        - Bucket configurado.
        - Prefixo 'app' para organizar a pasta interna no storage.
        - Public URL limpa no formato 'domain/bucket'.
        O prefixo interno ('app') deve aparecer no storage, mas ser omitido da URL pública.
        """
        storage = MinioStorage(
            minio_host="s3.wasabisys.com",
            minio_access_key="access",
            minio_secret_key="secret",
            minio_bucket="meu-bucket",
            minio_object_name_prefix="meu_prefix",
            minio_public_url="https://meudominio.com/meu-bucket",
            location="us-east-1",
        )

        # 1. Verifica se o caminho interno do objeto no Wasabi inclui a pasta 'meu_prefix'
        full_name = storage.get_full_object_name("documento.pdf")
        self.assertEqual(full_name, "meu_prefix/documento.pdf")

        # 2. Verifica se a URI pública gerada usa o domínio limpo (sem vazar a pasta 'app')
        uri = storage.get_uri("documento.pdf")
        self.assertEqual(uri, "https://meudominio.com/meu-bucket/documento.pdf")
        
        # Garante que o cliente MinIO não foi acionado para gerar URL assinada desnecessariamente
        mock_minio_class.return_value.presigned_get_object.assert_not_called()

    @patch("files_storage.minio.Minio")
    def test_generic_scenario_without_public_url_and_with_meu_prefix(self, mock_minio_class):
        """
        Cenário Genérico (Sem public_url):
        - Bucket configurado.
        - Prefixo 'meu_prefix' presente.
        - public_url ausente (None).
        A URI deve ser gerada via presigned do MinIO apontando para o caminho completo com o prefixo 'meu'.
        """
        mock_client = MagicMock()
        mock_client.presigned_get_object.return_value = (
            "https://s3.wasabisys.com/meu-bucket/meu_prefix/documento.pdf?signature=xyz"
        )
        
        storage = MinioStorage(
            minio_host="s3.wasabisys.com",
            minio_access_key="access",
            minio_secret_key="secret",
            minio_bucket="meu-bucket",
            minio_object_name_prefix="meu_prefix",
            minio_public_url=None,
            location="us-east-1",
        )
        storage._client_instance = mock_client

        # O caminho interno considera a pasta 'meu_prefix'
        self.assertEqual(storage.get_full_object_name("documento.pdf"), "meu_prefix/documento.pdf")

        # A URI assinada deve respeitar a estrutura de pastas do Wasabi (com 'meu_prefix')
        uri = storage.get_uri("documento.pdf")
        self.assertEqual(uri, "https://s3.wasabisys.com/meu-bucket/meu_prefix/documento.pdf")
        
        mock_client.presigned_get_object.assert_called_once_with(
            "meu-bucket", "meu_prefix/documento.pdf"
        )

    @patch("files_storage.minio.Minio")
    def test_storage_without_prefix_and_without_public_url(self, mock_minio_class):
        """
        Cenário sem prefixo (raiz do bucket) e sem public_url:
        - bucket obrigatório preenchido.
        - object_name_prefix vazio ou None.
        - public_url ausente.
        """
        mock_client = MagicMock()
        mock_client.presigned_get_object.return_value = (
            "https://s3.wasabisys.com/meu-bucket/documento.pdf?signature=xyz"
        )
        
        for empty_prefix in [None, ""]:
            with self.subTest(empty_prefix=empty_prefix):
                storage = MinioStorage(
                    minio_host="s3.wasabisys.com",
                    minio_access_key="access",
                    minio_secret_key="secret",
                    minio_bucket="meu-bucket",
                    minio_object_name_prefix=empty_prefix,
                    minio_public_url=None,
                    location="us-east-1",
                )
                storage._client_instance = mock_client

                self.assertEqual(storage.get_full_object_name("documento.pdf"), "documento.pdf")
                
                uri = storage.get_uri("documento.pdf")
                self.assertEqual(uri, "https://s3.wasabisys.com/meu-bucket/documento.pdf")


if __name__ == "__main__":
    unittest.main()
