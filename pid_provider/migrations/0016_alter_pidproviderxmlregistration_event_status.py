from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pid_provider", "0015_pidprovidersetting"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pidproviderxmlregistration",
            name="event_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("created", "created"),
                    ("updated", "updated"),
                    ("skipped", "skipped"),
                    ("forbidden", "forbidden"),
                    ("conflict", "conflict"),
                    ("unmatched", "unmatched"),
                    ("multiple", "multiple"),
                    ("bad_request", "bad_request"),
                    ("error", "error"),
                ],
                max_length=15,
                null=True,
                verbose_name="Event status",
            ),
        ),
    ]
