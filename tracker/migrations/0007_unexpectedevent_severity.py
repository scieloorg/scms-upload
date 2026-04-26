from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0006_tasktracker_total_processed_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="unexpectedevent",
            name="severity",
            field=models.CharField(
                choices=[
                    ("ERROR", "error"),
                    ("WARNING", "warning"),
                    ("INFO", "info"),
                    ("EXCEPTION", "exception"),
                ],
                default="EXCEPTION",
                max_length=10,
                verbose_name="Severity",
            ),
        ),
        migrations.AddIndex(
            model_name="unexpectedevent",
            index=models.Index(
                fields=["severity"],
                name="tracker_unexpectedevent_severity_idx",
            ),
        ),
    ]
