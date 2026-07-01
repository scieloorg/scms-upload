# coding: utf-8
import hashlib
import json
import logging
import os
from mimetypes import types_map
from tempfile import NamedTemporaryFile, TemporaryDirectory

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


def get_mimetype(file_path):
    name, ext = os.path.splitext(file_path)
    return types_map.get(ext, "application/octet-stream")


class SHA1Error(Exception): ...


class MinioStorageFPutContentError(Exception): ...


class MinioStorageFPutError(Exception): ...


class MinioStorageGetUriError(Exception): ...


class MinioStorageRegisterError(Exception): ...


class MinioStorageFgetError(Exception): ...


class MinioStorageGetZipFileItemsError(Exception): ...


class MinioStorageCreateBucketError(Exception): ...


class MinioStorageSetBucketPolicyError(Exception): ...


class MinioStorageNoSuchBucketError(Exception): ...


def _create_tmp_file(content=None):
    """
    Cria um arquivo temporário e se fornecido adiciona o conteúdo.
    Retorna a rota do arquivo criado

    Parameters
    ----------
    content : str
        conteúdo do arquivo

    Returns
    -------
    str
    """
    tf = NamedTemporaryFile(delete=False)
    if content:
        with open(tf.name, "wb") as fp:
            fp.write(content)
    return tf.name


def sha1(path):
    logger.debug("Lendo arquivo: %s", path)
    _sum = hashlib.sha1()
    try:
        with open(path, "rb") as file:
            while True:
                chunk = file.read(1024)
                if not chunk:
                    break
                _sum.update(chunk)
        return _sum.hexdigest()
    except (ValueError, FileNotFoundError) as e:
        raise SHA1Error("%s: %s" % (path, e))


class MinioStorage:
    def __init__(
        self,
        minio_host,
        minio_access_key,
        minio_secret_key,
        bucket,
        object_name_prefix,
        public_url,
        location,
        minio_secure=True,
        minio_http_client=None,
    ):
        self.bucket = bucket
        self.POLICY_READ_ONLY = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                    "Resource": [f"arn:aws:s3:::{self.bucket}"],
                },
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{self.bucket}/*"],
                },
            ],
        }
        self.minio_host = minio_host
        self.minio_access_key = minio_access_key
        self.minio_secret_key = minio_secret_key
        self.minio_secure = minio_secure
        self.http_client = minio_http_client
        self._client_instance = None
        self.location = location
        self.object_name_prefix = object_name_prefix
        self.public_url = public_url

    @property
    def _client(self):
        if not self._client_instance:
            # Initialize minioClient with an endpoint and access/secret keys
            self._client_instance = Minio(
                self.minio_host,
                access_key=self.minio_access_key,
                secret_key=self.minio_secret_key,
                secure=self.minio_secure,
                http_client=self.http_client,
            )
        return self._client_instance

    def _create_bucket(self):
        try:
            # Make a bucket with the make_bucket API call.
            self._client.make_bucket(self.bucket, location=self.location)
        except Exception as e:
            raise MinioStorageCreateBucketError(
                "Unable to create bucket %s %s %s" % (self.bucket, type(e), e)
            )

    def _set_bucket_policy(self):
        try:
            self._client.set_bucket_policy(
                self.bucket, json.dumps(self.POLICY_READ_ONLY)
            )
        except Exception as e:
            raise MinioStorageSetBucketPolicyError(
                "Unable to set bucket policy %s %s %s" % (self.bucket, type(e), e)
            )

    def get_full_object_name(self, object_name):
        if self.object_name_prefix:
            return f"{self.object_name_prefix}/{object_name}"
        return object_name

    def get_uri(self, object_name: str) -> str:
        """
        Obtém o URI do arquivo

        Parameters
        ----------
        object_name : str
            rota do arquivo, formada por subdirs e nome do arquivo

        Returns
        -------
        str

        Raises
        ------
        MinioStorageGetUriError
        """
        try:
            if self.public_url:
                return f"{self.public_url}/{object_name}"
            url = self._client.presigned_get_object(self.bucket, self.get_full_object_name(object_name))
            return url.split("?")[0]
        except Exception as e:
            raise MinioStorageGetUriError(
                "Unable to get uri %s %s %s %s %s"
                % (self.bucket, self.object_name_prefix, object_name, type(e), e)
            )

    def _no_such_bucket_error(self, err):
        """
        Identifica se o código de erro está relacionado a ausência de bucket

        Parameters
        ----------
        err : Exception

        Returns
        -------
        boolean
        """
        return err.code == "NoSuchBucket"

    def fput(self, file_path, object_name, mimetype=None) -> str:
        """
        Registra o arquivo no Minio e retorna o URI.
        No entanto, se houver a exceção de que o bucket não existe,
        o cria e tenta novamente o registro

        Parameters
        ----------
        file_path : str
            rota do arquivo fonte
        object_name : str
            rota das sub-pastas a serem criadas / atualizadas no Minio
        mimetype : str
            indica se o nome do arquivo será mantido ou será criado um novo

        Returns
        -------
        str

        Raises
        ------
        MinioStorageFPutError
        """
        mimetype = mimetype or get_mimetype(file_path)
    
        try:
            self._client.fput_object(
                self.bucket,
                object_name=self.get_full_object_name(object_name),
                file_path=file_path,
                content_type=mimetype,
            )
            return self.get_uri(object_name)

        except S3Error as e:
            logger.error(e)
            if self._no_such_bucket_error(e):
                self._create_bucket()
                self._set_bucket_policy()
                return self.fput(file_path, object_name, mimetype)

            raise e

    def fput_content(self, content, mimetype, object_name) -> str:
        """
        Cria um arquivo com o conteúdo fornecido,
        registra-o no Minio e retorna o URI.

        Parameters
        ----------
        content : bytes
            conteúdo do arquivo
        mimetype : str
            indica se o nome do arquivo será mantido ou será criado um novo
        object_name : str
            rota das sub-pastas a serem criadas / atualizadas no Minio

        Returns
        -------
        str

        Raises
        ------
        MinioStorageFPutContentError
        """
        try:
            with TemporaryDirectory() as targetdir:
                file_path = os.path.join(targetdir, os.path.basename(object_name))
                with open(file_path, "wb") as fp:
                    fp.write(content)
                return self.fput(file_path, object_name, mimetype)
        except Exception as e:
            raise MinioStorageFPutContentError(
                "Unable to fput content %s %s %s" % (object_name, type(e), e)
            )

    def remove(self, object_name: str) -> None:
        """
        Remove an object

        Parameters
        ----------
        object_name : str
            rota do arquivo no Minio

        """
        # https://docs.min.io/docs/python-client-api-reference.html#remove_object
        return self._client.remove_object(self.bucket, self.get_full_object_name(object_name))

    def fget(self, object_name, downloaded_file_path=None):
        """
        Obtém o arquivo, dado object_name

        Parameters
        ----------
        object_name : str
            rota do arquivo no Minio
        downloaded_file_path : str
            rota do destino do arquivo, que é criado se não foi fornecido

        Raises
        ------
        MinioStorageFgetError
        """
        try:
            if not downloaded_file_path:
                downloaded_file_path = _create_tmp_file()

            # https://docs.min.io/docs/python-client-api-reference.html#fget_object
            self._client.fget_object(
                self.bucket, self.get_full_object_name(object_name), downloaded_file_path
            )

            return downloaded_file_path
        except Exception as e:
            raise MinioStorageFgetError(
                "Unable to fget %s %s %s" % (object_name, type(e), e)
            )
