from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("upload", "0015_preserve_validation_messages"),
    ]

    operations = [
        migrations.AlterField(
            model_name="package",
            name="public_ws_pubdate",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Production publication date"
            ),
        ),
        migrations.AlterField(
            model_name="package",
            name="public_ws_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("unreleased", "unreleased"),
                    ("published", "published"),
                    ("depublished", "depublished"),
                ],
                default="unreleased",
                max_length=15,
                null=True,
                verbose_name="Production publication status",
            ),
        ),
        migrations.AlterField(
            model_name="package",
            name="qa_decision",
            field=models.CharField(
                blank=True,
                choices=[
                    ("depublished", "Depublish"),
                    ("pending-correction", "Request correction"),
                    ("pending-qa-decision", "Assign quality review"),
                    ("ready-to-preview", "Publish on QA website"),
                    ("ready-to-publish", "Publish in Production"),
                ],
                help_text="Make a decision about the package or choose the analyst who will decide it",
                max_length=32,
                null=True,
                verbose_name="Quality analysis decision",
            ),
        ),
        migrations.AlterField(
            model_name="package",
            name="status",
            field=models.CharField(
                choices=[
                    ("required-erratum", "Erratum required"),
                    ("required-update", "Update required"),
                    ("submitted", "Submitted"),
                    ("enqueued-for-validation", "Processing"),
                    ("validated-with-errors", "Validation issues found"),
                    ("pending-qa-decision", "Awaiting quality review"),
                    ("pending-correction", "Awaiting corrections"),
                    ("unexpected", "Unexpected submission"),
                    ("ready-to-preview", "Publication on QA website authorized"),
                    ("preview", "Published in QA"),
                    ("ready-to-publish", "Publication in Production authorized"),
                    ("published", "Published in Production"),
                    ("archived", "Archived"),
                ],
                default="enqueued-for-validation",
                max_length=32,
                verbose_name="Status",
            ),
        ),
    ]
