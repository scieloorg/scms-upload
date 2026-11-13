from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("issue", "0004_issue_issue_pid_suffix_issue_order_toc_tocsection"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tocsection",
            name="group",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
