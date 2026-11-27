from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("article", "0011_alter_articlecollection_article_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="data_availability_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("data-available", "Data available"),
                    ("data-available-upon-request", "Data available upon request"),
                    ("data-not-available", "Data not available"),
                    ("data-in-article", "Data in article"),
                    ("uninformed", "Uninformed"),
                    ("absent", "Absent"),
                    ("invalid", "Invalid"),
                ],
                max_length=32,
                null=True,
                verbose_name="Data availability status",
            ),
        ),
    ]
