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
        Busca uma configuração existente pelo nome ou cria uma nova com os parâmetros fornecidos.
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
        Retorna a configuração correspondente ao nome ou None se não existir.
        """
        try:
            return cls.objects.get(name=name)
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_files_storage(cls, name, minio_http_client=None):
        """
        Instancia e retorna um objeto MinioStorage pronto para uso do SDK cliente.
        Caso a configuração nomeada não exista, tenta recuperar a primeira disponível no banco.
        """
        try:
            obj = cls.objects.get(name=name)
        except cls.DoesNotExist:
            # Fallback: pega qualquer configuração ativa caso o nome específico falhe
            obj = cls.objects.filter(host__isnull=False).first()

        if not obj:
            raise cls.DoesNotExist(f"Minio Configuration not found")

        # Nota de Alerta: Caso nenhum objeto seja encontrado no fallback, a linha abaixo quebrará (AttributeError).
        # É uma boa prática garantir que obj não seja nulo aqui.
        return MinioStorage(
            minio_host=obj.host,
            minio_access_key=obj.access_key,
            minio_secret_key=obj.secret_key,
            # Se houver host_root_dir, ele assume o papel do bucket principal na conexão do Minio Client
            bucket=obj.host_root_dir or obj.bucket,
            object_name_prefix=obj.object_name_prefix,
            public_url=obj.public_url,
            location=obj.location,
            minio_secure=obj.secure,
            minio_http_client=minio_http_client,
        )
    
    @property
    def object_name_prefix(self):
        """
        Se o 'host_root_dir' existir, a lógica de estrutura se inverte: o bucket físico
        passa a agir como uma subpasta (prefixo) dentro da estrutura principal do storage.
        """
        if self.host_root_dir:
            return self.bucket
        return ""

    @property
    def public_url(self):
        """
        Gera a URL base pública de leitura dos arquivos.
        Se não houver uma URL pública customizada definida, constrói uma baseada no host e protocolo.
        Se houver prefixo (bucket como subpasta), anexa-o ao final da URL.
        """
        public_base_url = self.public_base_url
        
        # Constrói a URL padrão (http://host ou https://host) se public_base_url estiver em branco
        if not public_base_url:
            suffix = "s" if self.secure else ""
            public_base_url = f"http{suffix}://{self.host}"
            
        # Adiciona o prefixo do bucket à URL se estivermos usando a estrutura invertida (host_root_dir)
        if self.object_name_prefix:
            return f"{public_base_url}/{self.object_name_prefix}"
            
        return public_base_url


class FileLocation(CommonControlField):
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
