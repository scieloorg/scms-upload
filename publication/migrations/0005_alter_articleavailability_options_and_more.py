# Generated by Django 5.0.3 on 2025-05-17 15:47

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("publication", "0004_alter_articleavailability_options_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="articleavailability",
            options={},
        ),
        migrations.RemoveField(
            model_name="articleavailability",
            name="published_percentage",
        ),
        migrations.AddField(
            model_name="articleavailability",
            name="completed",
            field=models.BooleanField(default=False),
        ),
    ]
