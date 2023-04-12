# Generated by Django 3.2.12 on 2023-03-03 10:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('location', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='city',
            name='name',
            field=models.TextField(verbose_name='City Name'),
        ),
        migrations.AlterField(
            model_name='country',
            name='name',
            field=models.TextField(blank=True, null=True, verbose_name='Country Name'),
        ),
        migrations.AlterField(
            model_name='state',
            name='name',
            field=models.TextField(blank=True, null=True, verbose_name='State Name'),
        ),
    ]