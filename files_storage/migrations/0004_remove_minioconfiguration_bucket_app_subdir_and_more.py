# Generated by Django 5.0.3 on 2025-06-03 22:43

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("files_storage", "0003_alter_filelocation_basename"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="minioconfiguration",
            name="bucket_app_subdir",
        ),
        migrations.AddField(
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
                ],
                default="sa-east-1",
                max_length=16,
                null=True,
                verbose_name="Location",
            ),
        ),
    ]
