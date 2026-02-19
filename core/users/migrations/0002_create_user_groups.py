# Generated manually for user groups setup

from django.contrib.auth.models import Group
from django.db import migrations


def create_user_groups(apps, schema_editor):
    """Create default user groups."""
    groups = [
        "Superadmin",
        "Admin Coleção",
        "Analista",
        "Produtor XML",
        "Gestor de Periódico",
        "Gestor de Empresa",
        "Revisor",
    ]
    
    for group_name in groups:
        Group.objects.get_or_create(name=group_name)


def remove_user_groups(apps, schema_editor):
    """Remove user groups."""
    groups = [
        "Superadmin",
        "Admin Coleção",
        "Analista",
        "Produtor XML",
        "Gestor de Periódico",
        "Gestor de Empresa",
        "Revisor",
    ]
    
    Group.objects.filter(name__in=groups).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_user_groups, remove_user_groups),
    ]
