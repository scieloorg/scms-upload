# Generated by Django 5.0.3 on 2024-08-23 00:00

import django.db.models.deletion
import modelcluster.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("package", "0002_alter_spspkg_options"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="spspkg",
            name="components",
        ),
        migrations.RemoveField(
            model_name="spspkg",
            name="scheduled",
        ),
        migrations.AlterField(
            model_name="spspkg",
            name="origin",
            field=models.CharField(
                blank=True,
                choices=[("MIGRATION", "MIGRATION"), ("UPLOAD", "UPLOAD")],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="spspkgcomponent",
            name="legacy_uri",
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AlterField(
            model_name="spspkgcomponent",
            name="sps_pkg",
            field=modelcluster.fields.ParentalKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="components",
                to="package.spspkg",
            ),
        ),
    ]
