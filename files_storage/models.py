from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel

from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from files_storage import exceptions
from files_storage.minio import MinioStorage

COUNTRY_REGION = (
    ("Brasil", "sa-east-1"),
    ("México", "us-west-1"),
    ("Colombia", "sa-east-1"),
    ("Chile", "sa-east-1"),
    ("Cuba", "us-east-1"),
    ("Argentina", "sa-east-1"),
    ("Perú", "sa-east-1"),
    ("Venezuela", "sa-east-1"),
    ("Costa Rica", "us-east-1"),
    ("Bolivia", "sa-east-1"),
    ("Uruguay", "sa-east-1"),
    ("Ecuador", "sa-east-1"),
    ("Paraguay", "sa-east-1"),
    ("España", "eu-south-1"),
    ("Portugal", "eu-west-1"),
    ("South Africa", "af-south-1"),
    ("West Indies", "us-east-1"),
    ("China", "ap-east-1"),
    ("Russia", "eu-north-1"),
    ("Panamá", "us-east-1"),
    ("República Dominicana", "us-east-1"),
)


class MinioConfiguration(CommonControlField):
    """
    Model para persistência e gerenciamento das configurações de integração
    com serviços de Object Storage (MinIO, S3, Wasabi, etc.).
    """

    # Identificador único da configuração (ex: 'website', 'journals')
    name = models.CharField(_("Name"), max_length=32, null=False, blank=False, default="website")

    # Endpoint do serviço de storage (sem o protocolo)
    host = models.CharField(_("Host"), max_length=64, null=True, blank=False, help_text=_("Endpoint do object storage para gravação (sem https://). Ex.: s3.wasabisys.com."))

    # Diretório/Bucket pai no servidor de destino
    host_root_dir = models.CharField(
        _("Host root dir"), max_length=32, null=True, blank=True,
        help_text=_("Diretório raíz no servidor que contém o bucket. Ex.: scielo")
    )

    # Nome do bucket onde os arquivos serão armazenados
    bucket = models.CharField(
        _("Bucket"), max_length=32, null=False, blank=False,
        default="upload",
        help_text=_("Bucket no object storage (MinIO/S3/Wasabi) onde os arquivos são fisicamente gravados. Ex.: upload")
    )

    # URL customizada para entrega pública de arquivos (ex: CDN ou Proxy)
    public_base_url = models.URLField(
        _("Public base URL"), max_length=500, null=True, blank=True, help_text=_("URL pública base usada para montar a URI de leitura salva no banco. Deve já incluir o caminho público completo até os objetos (inclusive qualquer prefixo), pois o host_root_dir não é reaplicado aqui. Ex.: https://minio.scielo.br. Se vazia, a URI é gerada via presigned URL do próprio object storage. Leitura e gravação são independentes: garanta que esta URL sirva o mesmo conteúdo gravado sob host_root_dir")
    )

    # Região geográfica do bucket (comum no AWS S3)
    location = models.CharField(
        _("Location"),
        max_length=20,
        null=True,
        blank=True,
        choices=COUNTRY_REGION,
        default="sa-east-1",
        help_text=_("Região usada ao criar o bucket (ex.: us-east-1). Deixe vazio se o provedor não exigir.")
    )

    # Credenciais de acesso
    access_key = models.CharField(_("Access key"), max_length=32, null=False, blank=False, default="*****")
    secret_key = models.CharField(_("Secret key"), max_length=64, null=False, blank=False, default="*****")

    # Indicar como False para uso no desenvolvimento (HTTP) e True para produção (HTTPS)
    secure = models.BooleanField(_("Secure"), default=False, help_text=_("Usar HTTPS na conexão com o object storage. Mantenha marcado em produção."))

    class Meta:
        indexes = [
            models.Index(fields=["name"]),  # Otimiza buscas pelo nome da configuração
        ]

    # Configuração dos painéis de exibição para a interface administrativa do Wagtail
    panels = [
        FieldPanel("name"),
        FieldPanel("host"),
        FieldPanel("host_root_dir"),
        FieldPanel("bucket"),
        FieldPanel("public_base_url"),
        FieldPanel("access_key"),
        FieldPanel("secret_key"),
        FieldPanel("secure"),
        FieldPanel("location"),
    ]

    # Define o formulário customizado usado no admin
    base_form_class = CoreAdminModelForm

    def __str__(self):
        return f"{self.host} {self.bucket}"

    def __unicode__(self):
        return f"{self.host} {self.bucket}"

    @classmethod
    def get_or_create(
        cls,
        name,
        host=None,
        access_key=None,
        secret_key=None,
        secure=None,
        bucket=None,
        host_root_dir=None,
        public_base_url=None,
        location=None,
        user=None,
    ):
        """
        Busca uma configuração existente pelo nome ou cria uma nova com os
        parâmetros fornecidos.

        Parameters
        ----------
        name : str
            Identificador único da configuração (ex.: 'website', 'journals').
        host : str, opcional
            Endpoint do object storage (sem protocolo).
        access_key : str, opcional
            Chave de acesso ao object storage.
        secret_key : str, opcional
            Chave secreta de acesso ao object storage.
        secure : bool, opcional
            Se True, conexão via HTTPS.
        bucket : str, opcional
            Nome do bucket físico onde os arquivos são gravados.
        host_root_dir : str, opcional
            Diretório raiz no servidor que contém o bucket.
        public_base_url : str, opcional
            URL pública base para leitura dos arquivos.
        location : str, opcional
            Região do bucket (choices em COUNTRY_REGION).
        user : User, opcional
            Usuário responsável pela criação (persistido em `creator`).

        Returns
        -------
        MinioConfiguration
            Instância existente (se `name` já cadastrado) ou recém-criada.

        Notas
        -----
        Se a configuração já existir, os parâmetros informados são
        ignorados e o registro existente é retornado sem atualização
        (não há upsert).
        """
        try:
            return cls.objects.get(name=name)
        except cls.DoesNotExist:
            files_storage = cls()
            files_storage.name = name
            files_storage.host = host
            files_storage.secure = secure
            files_storage.access_key = access_key
            files_storage.secret_key = secret_key
            files_storage.bucket = bucket
            files_storage.host_root_dir = host_root_dir
            files_storage.public_base_url = public_base_url
            files_storage.location = location
            files_storage.creator = user  # Atribui o usuário criador (herdado de CommonControlField)
            files_storage.save()
            return files_storage

    @classmethod
    def get(cls, name):
        """
        Retorna a configuração correspondente ao nome informado.

        Parameters
        ----------
        name : str
            Identificador da configuração a ser buscada.

        Returns
        -------
        MinioConfiguration or None
            A instância encontrada, ou None caso não exista configuração
            com o nome informado.
        """
        try:
            return cls.objects.get(name=name)
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_files_storage(cls, name, minio_http_client=None):
        """
        Instancia e retorna um objeto MinioStorage pronto para uso do
        SDK cliente, a partir da configuração persistida.

        Parameters
        ----------
        name : str
            Nome da configuração desejada (ex.: 'website').
        minio_http_client : HTTPClient, opcional
            Cliente HTTP customizado a ser injetado no MinioStorage
            (útil para testes ou configurações de proxy/timeout).

        Returns
        -------
        MinioStorage
            Instância configurada com host, credenciais, bucket, prefixo
            e URL pública resolvidos a partir do registro encontrado.

        Raises
        ------
        MinioConfiguration.DoesNotExist
            Se nenhuma configuração com `host` definido for encontrada,
            nem mesmo como fallback.

        Notas
        -----
        Caso a configuração nomeada não exista, tenta recuperar a
        primeira configuração disponível no banco que possua `host`
        preenchido (fallback).
        """
        try:
            obj = cls.objects.get(name=name)
        except cls.DoesNotExist:
            # Fallback: pega qualquer configuração ativa caso o nome específico falhe
            obj = cls.objects.filter(host__isnull=False).first()

        if not obj:
            raise cls.DoesNotExist(f"Minio Configuration not found")

        # Correção: usa o objeto instanciado 'obj.kwargs' em vez de 'self.kwargs'
        kwargs = obj.kwargs
        kwargs["minio_http_client"] = minio_http_client
        return MinioStorage(**kwargs)

    @property
    def kwargs(self):
        """
        Monta o dicionário de argumentos usado para instanciar
        MinioStorage a partir desta configuração.

        Returns
        -------
        dict
            Chaves compatíveis com o construtor de `MinioStorage`:
            minio_host, minio_access_key, minio_secret_key, minio_bucket,
            minio_object_name_prefix, minio_public_url, location e
            minio_secure. Não inclui `minio_http_client` — deve ser
            adicionado pelo chamador quando necessário.
        """
        return dict(
            minio_host=self.host,
            minio_access_key=self.access_key,
            minio_secret_key=self.secret_key,
            # Se houver host_root_dir, ele assume o papel do bucket principal na conexão do Minio Client
            minio_bucket=self.minio_bucket,
            minio_object_name_prefix=self.minio_object_name_prefix,
            minio_public_url=self.minio_public_url,
            location=self.location,
            minio_secure=self.secure,
        )

    @property
    def minio_bucket(self):
        """
        Resolve qual valor deve ser usado como bucket físico de conexão
        com o Minio Client.

        Returns
        -------
        str
            `host_root_dir`, se definido (nesse caso o bucket configurado
            passa a atuar como prefixo dentro dele); caso contrário,
            retorna `bucket`.
        """
        if self.host_root_dir:
            return self.host_root_dir
        return self.bucket

    @property
    def minio_object_name_prefix(self):
        """
        Resolve o prefixo a ser aplicado aos nomes de objeto gravados.

        Returns
        -------
        str
            `bucket`, quando `host_root_dir` está definido (estrutura
            invertida, em que o bucket configurado age como subpasta
            dentro do host_root_dir); string vazia caso contrário.
        """
        if self.host_root_dir:
            return self.bucket
        return ""

    @property
    def minio_public_url(self):
        """
        Resolve a URL base pública usada para leitura dos arquivos.

        Returns
        -------
        str
            `public_base_url`, se estiver definida (usada exatamente
            como informada, sem concatenação adicional). Caso contrário,
            monta a URL a partir de `host` e `secure` (http/https) e
            anexa `minio_bucket` como subcaminho.

        Notas
        -----
        `public_base_url` deve já incluir qualquer prefixo necessário
        até os objetos — `host_root_dir`/`bucket` não são reaplicados
        sobre ela. Essa regra só se aplica ao fallback (quando
        `public_base_url` está vazia).
        """
        public_base_url = self.public_base_url
        if public_base_url:
            # url fornecida é priorizada
            return public_base_url
        suffix = "s" if self.secure else ""
        public_base_url = f"http{suffix}://{self.host}"
        return f"{public_base_url}/{self.minio_bucket}"


class FileLocation(CommonControlField):
    """
    Model que registra a localização (URI) de um arquivo já gravado
    no object storage, permitindo referenciá-lo por outras entidades
    do sistema (ex.: documentos, imagens, anexos).
    """

    basename = models.CharField(_("Basename"), max_length=100, null=True, blank=True)
    uri = models.URLField(_("URI"), null=True, blank=True, max_length=500)

    autocomplete_search_field = "uri"

    class Meta:
        indexes = [
            models.Index(fields=["uri"]),
        ]

    panels = [
        FieldPanel("basename"),
        FieldPanel("uri"),
    ]

    def __unicode__(self):
        return f"{self.uri} {self.created}"

    def __str__(self):
        return f"{self.uri} {self.created}"

    @classmethod
    def get_or_create(cls, creator, uri, basename=None):
        """
        Busca um registro existente pela URI ou cria um novo.

        Parameters
        ----------
        creator : User
            Usuário responsável pela criação do registro (usado apenas
            quando um novo objeto é criado).
        uri : str
            URI pública/identificadora do arquivo. Usada como chave de
            busca.
        basename : str, opcional
            Nome base do arquivo (ex.: nome original, sem caminho).

        Returns
        -------
        FileLocation
            Instância existente com a `uri` informada, ou recém-criada.

        Raises
        ------
        exceptions.MinioFileGetOrCreateError
            Se ocorrer qualquer erro inesperado durante a criação do
            registro (exceto DoesNotExist, que é tratado normalmente).
        """
        try:
            return cls.objects.get(uri=uri)
        except cls.DoesNotExist:
            obj = cls()
            obj.uri = uri
            obj.basename = basename
            obj.creator = creator
            obj.save()
            return obj
        except Exception as e:
            raise exceptions.MinioFileGetOrCreateError(
                "Unable to create file: %s %s %s" % (type(e), e, uri)
            )