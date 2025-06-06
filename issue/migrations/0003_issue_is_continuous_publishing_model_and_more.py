# Generated by Django 5.0.3 on 2024-07-04 16:06

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("issue", "0002_alter_issue_number_alter_issue_supplement_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="issue",
            name="is_continuous_publishing_model",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="issue",
            name="total_documents",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
