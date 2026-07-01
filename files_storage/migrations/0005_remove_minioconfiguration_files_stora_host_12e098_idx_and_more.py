class Migration(migrations.Migration):
    dependencies = [
        ("files_storage", "0004_remove_minioconfiguration_bucket_app_subdir_and_more"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="minioconfiguration",
            name="files_stora_host_12e098_idx",
        ),
        migrations.RemoveIndex(
            model_name="minioconfiguration",
            name="files_stora_bucket__8a0a27_idx",
        ),
        # Renomeia preservando os dados já gravados em bucket_root
        migrations.RenameField(
            model_name="minioconfiguration",
            old_name="bucket_root",
            new_name="bucket",
        ),
        # Só agora ajusta as características do campo (default, help_text,
        # null/blank), sem afetar os valores já existentes
        migrations.AlterField(
            model_name="minioconfiguration",
            name="bucket",
            field=models.CharField(
                default="upload",
                help_text="Bucket no object storage (MinIO/S3/Wasabi) onde os arquivos são fisicamente gravados. Ex.: upload",
                max_length=32,
                verbose_name="Bucket",
            ),
        ),
        migrations.AddField(
            model_name="minioconfiguration",
            name="host_root_dir",
            field=models.CharField(
                blank=True,
                help_text="Diretório raíz no servidor que contém o bucket. Ex.: scielo",
                max_length=32,
                null=True,
                verbose_name="Host root dir",
            ),
        ),
        migrations.AddField(
            model_name="minioconfiguration",
            name="public_base_url",
            field=models.URLField(
                blank=True,
                help_text="URL pública base usada para montar a URI de leitura salva no banco. Deve já incluir o caminho público completo até os objetos (inclusive qualquer prefixo), pois o host_root_dir não é reaplicado aqui. Ex.: https://minio.scielo.br. Se vazia, a URI é gerada via presigned URL do próprio object storage. Leitura e gravação são independentes: garanta que esta URL sirva o mesmo conteúdo gravado sob host_root_dir",
                max_length=500,
                null=True,
                verbose_name="Public base URL",
            ),
        ),
        migrations.AlterField(
            model_name="filelocation",
            name="uri",
            field=models.URLField(
                blank=True, max_length=500, null=True, verbose_name="URI"
            ),
        ),
        migrations.AlterField(
            model_name="minioconfiguration",
            name="access_key",
            field=models.CharField(
                default="*****", max_length=32, verbose_name="Access key"
            ),
        ),
        migrations.AlterField(
            model_name="minioconfiguration",
            name="host",
            field=models.CharField(
                help_text="Endpoint do object storage para gravação (sem https://). Ex.: s3.wasabisys.com.",
                max_length=64,
                null=True,
                verbose_name="Host",
            ),
        ),
        migrations.AlterField(
            model_name="minioconfiguration",
            name="location",
            field=models.CharField(
                blank=True,
                choices=[
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
                ],
                default="sa-east-1",
                help_text="Região usada ao criar o bucket (ex.: us-east-1). Deixe vazio se o provedor não exigir.",
                max_length=20,
                null=True,
                verbose_name="Location",
            ),
        ),
        migrations.AlterField(
            model_name="minioconfiguration",
            name="name",
            field=models.CharField(
                default="website", max_length=32, verbose_name="Name"
            ),
        ),
        migrations.AlterField(
            model_name="minioconfiguration",
            name="secret_key",
            field=models.CharField(
                default="*****", max_length=64, verbose_name="Secret key"
            ),
        ),
        migrations.AlterField(
            model_name="minioconfiguration",
            name="secure",
            field=models.BooleanField(
                default=False,
                help_text="Usar HTTPS na conexão com o object storage. Mantenha marcado em produção.",
                verbose_name="Secure",
            ),
        ),
    ]