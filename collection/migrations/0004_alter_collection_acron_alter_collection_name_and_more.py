# Generated by Django 5.0.3 on 2025-04-30 22:03

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("collection", "0003_websiteconfigurationendpoint"),
    ]

    operations = [
        migrations.AlterField(
            model_name="collection",
            name="acron",
            field=models.CharField(
                blank=True, max_length=16, null=True, verbose_name="Collection Acronym"
            ),
        ),
        migrations.AlterField(
            model_name="collection",
            name="name",
            field=models.CharField(
                blank=True, max_length=64, null=True, verbose_name="Collection Name"
            ),
        ),
        migrations.AlterField(
            model_name="language",
            name="code2",
            field=models.CharField(
                blank=True, max_length=5, null=True, verbose_name="Language code 2"
            ),
        ),
        migrations.AlterField(
            model_name="language",
            name="name",
            field=models.CharField(
                blank=True, max_length=64, null=True, verbose_name="Language Name"
            ),
        ),
    ]
