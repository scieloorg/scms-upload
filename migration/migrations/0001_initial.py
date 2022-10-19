# Generated by Django 3.2.12 on 2022-12-22 17:54

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('collection', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='MigratedData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, verbose_name='Creation date')),
                ('updated', models.DateTimeField(auto_now=True, verbose_name='Last update date')),
                ('isis_updated_date', models.CharField(blank=True, max_length=8, null=True, verbose_name='ISIS updated date')),
                ('isis_created_date', models.CharField(blank=True, max_length=8, null=True, verbose_name='ISIS created date')),
                ('data', models.JSONField(blank=True, null=True)),
                ('status', models.CharField(choices=[('TO_MIGRATE', 'To migrate'), ('TO_IGNORE', 'To ignore'), ('IMPORTED', 'Imported'), ('PUBLISHED', 'Publicado')], default='TO_MIGRATE', max_length=20, verbose_name='Status')),
                ('creator', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='migrateddata_creator', to=settings.AUTH_USER_MODEL, verbose_name='Creator')),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='migrateddata_last_mod_user', to=settings.AUTH_USER_MODEL, verbose_name='Updater')),
            ],
        ),
        migrations.CreateModel(
            name='DocumentMigration',
            fields=[
                ('migrateddata_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='migration.migrateddata')),
                ('files_status', models.CharField(choices=[('TO_MIGRATE', 'To migrate'), ('TO_IGNORE', 'To ignore'), ('IMPORTED', 'Imported'), ('PUBLISHED', 'Publicado')], default='TO_MIGRATE', max_length=20, verbose_name='Status')),
            ],
            bases=('migration.migrateddata',),
        ),
        migrations.CreateModel(
            name='IssueMigration',
            fields=[
                ('migrateddata_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='migration.migrateddata')),
                ('files_status', models.CharField(choices=[('TO_MIGRATE', 'To migrate'), ('TO_IGNORE', 'To ignore'), ('IMPORTED', 'Imported'), ('PUBLISHED', 'Publicado')], default='TO_MIGRATE', max_length=20, verbose_name='Status')),
            ],
            bases=('migration.migrateddata',),
        ),
        migrations.CreateModel(
            name='JournalMigration',
            fields=[
                ('migrateddata_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='migration.migrateddata')),
            ],
            bases=('migration.migrateddata',),
        ),
        migrations.CreateModel(
            name='MigrationFailure',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, verbose_name='Creation date')),
                ('updated', models.DateTimeField(auto_now=True, verbose_name='Last update date')),
                ('action_name', models.CharField(max_length=255, verbose_name='Action')),
                ('object_name', models.CharField(max_length=255, verbose_name='Object')),
                ('pid', models.CharField(max_length=23, verbose_name='Item PID')),
                ('exception_type', models.CharField(max_length=255, verbose_name='Exception Type')),
                ('exception_msg', models.CharField(max_length=555, verbose_name='Exception Msg')),
                ('traceback', models.JSONField(blank=True, null=True)),
                ('creator', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='migrationfailure_creator', to=settings.AUTH_USER_MODEL, verbose_name='Creator')),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='migrationfailure_last_mod_user', to=settings.AUTH_USER_MODEL, verbose_name='Updater')),
            ],
        ),
        migrations.CreateModel(
            name='MigrationConfiguration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, verbose_name='Creation date')),
                ('updated', models.DateTimeField(auto_now=True, verbose_name='Last update date')),
                ('classic_website_config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collection.classicwebsiteconfiguration')),
                ('creator', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='migrationconfiguration_creator', to=settings.AUTH_USER_MODEL, verbose_name='Creator')),
                ('files_storage_config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collection.filesstorageconfiguration')),
                ('new_website_config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collection.newwebsiteconfiguration')),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='migrationconfiguration_last_mod_user', to=settings.AUTH_USER_MODEL, verbose_name='Updater')),
            ],
        ),
        migrations.AddIndex(
            model_name='migrationfailure',
            index=models.Index(fields=['object_name'], name='migration_m_object__d510e6_idx'),
        ),
        migrations.AddIndex(
            model_name='migrationfailure',
            index=models.Index(fields=['pid'], name='migration_m_pid_c2722d_idx'),
        ),
        migrations.AddIndex(
            model_name='migrationfailure',
            index=models.Index(fields=['action_name'], name='migration_m_action__031324_idx'),
        ),
        migrations.AddIndex(
            model_name='migrationconfiguration',
            index=models.Index(fields=['classic_website_config'], name='migration_m_classic_518e10_idx'),
        ),
        migrations.AddIndex(
            model_name='migrateddata',
            index=models.Index(fields=['status'], name='migration_m_status_9aee95_idx'),
        ),
        migrations.AddIndex(
            model_name='migrateddata',
            index=models.Index(fields=['isis_updated_date'], name='migration_m_isis_up_c84dc4_idx'),
        ),
        migrations.AddField(
            model_name='journalmigration',
            name='scielo_journal',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collection.scielojournal'),
        ),
        migrations.AddField(
            model_name='issuemigration',
            name='scielo_issue',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collection.scieloissue'),
        ),
        migrations.AddField(
            model_name='documentmigration',
            name='scielo_document',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collection.scielodocument'),
        ),
        migrations.AddIndex(
            model_name='journalmigration',
            index=models.Index(fields=['scielo_journal'], name='migration_j_scielo__866f9c_idx'),
        ),
        migrations.AddIndex(
            model_name='issuemigration',
            index=models.Index(fields=['scielo_issue'], name='migration_i_scielo__566663_idx'),
        ),
        migrations.AddIndex(
            model_name='documentmigration',
            index=models.Index(fields=['scielo_document'], name='migration_d_scielo__1f935e_idx'),
        ),
    ]