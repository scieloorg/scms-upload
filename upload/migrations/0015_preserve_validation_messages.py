from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("upload", "0014_regras_por_colecao")]

    operations = [
        migrations.AlterField(
            model_name="basexmlvalidationresult",
            name="message",
            field=models.TextField(blank=True, null=True, verbose_name="Message"),
        ),
        migrations.AlterField(
            model_name="pkgvalidationresult",
            name="message",
            field=models.TextField(blank=True, null=True, verbose_name="Message"),
        ),
        migrations.AlterField(
            model_name="xmlerror",
            name="advice",
            field=models.TextField(blank=True, null=True, verbose_name="Advice"),
        ),
    ]
