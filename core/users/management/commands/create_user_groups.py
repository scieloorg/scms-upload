"""
Management command to create default user groups for the system.
"""

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from core.users.user_groups import UserGroups, GROUP_DESCRIPTIONS


class Command(BaseCommand):
    help = "Create default user groups with appropriate permissions"

    def handle(self, *args, **options):
        """Create user groups."""
        self.stdout.write("Creating user groups...")
        
        created_count = 0
        updated_count = 0
        
        # Define groups and their basic permissions
        groups_config = [
            {
                'name': UserGroups.SUPERADMIN,
                'description': GROUP_DESCRIPTIONS[UserGroups.SUPERADMIN],
                'permissions': []  # Superadmin uses is_superuser flag
            },
            {
                'name': UserGroups.ADMIN_COLLECTION,
                'description': GROUP_DESCRIPTIONS[UserGroups.ADMIN_COLLECTION],
                'permissions': []  # Will be configured through APP_PERMISSIONS
            },
            {
                'name': UserGroups.ANALYST,
                'description': GROUP_DESCRIPTIONS[UserGroups.ANALYST],
                'permissions': []
            },
            {
                'name': UserGroups.XML_PRODUCER,
                'description': GROUP_DESCRIPTIONS[UserGroups.XML_PRODUCER],
                'permissions': []
            },
            {
                'name': UserGroups.JOURNAL_MANAGER,
                'description': GROUP_DESCRIPTIONS[UserGroups.JOURNAL_MANAGER],
                'permissions': []
            },
            {
                'name': UserGroups.COMPANY_MANAGER,
                'description': GROUP_DESCRIPTIONS[UserGroups.COMPANY_MANAGER],
                'permissions': []
            },
            {
                'name': UserGroups.REVIEWER,
                'description': GROUP_DESCRIPTIONS[UserGroups.REVIEWER],
                'permissions': []
            },
        ]
        
        for group_config in groups_config:
            group, created = Group.objects.get_or_create(
                name=group_config['name']
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Created group: {group_config['name']}"
                    )
                )
                created_count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"• Group already exists: {group_config['name']}"
                    )
                )
                updated_count += 1
            
            # Clear existing permissions and add new ones
            group.permissions.clear()
            
            # Add specific permissions if defined
            for perm_codename in group_config['permissions']:
                try:
                    permission = Permission.objects.get(codename=perm_codename)
                    group.permissions.add(permission)
                except Permission.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Warning: Permission '{perm_codename}' not found"
                        )
                    )
        
        self.stdout.write("\n" + "="*50)
        self.stdout.write(
            self.style.SUCCESS(
                f"\nSummary:\n"
                f"  Created: {created_count} groups\n"
                f"  Updated: {updated_count} groups\n"
                f"  Total: {created_count + updated_count} groups"
            )
        )
        self.stdout.write("\n" + "="*50)
        
        self.stdout.write(
            self.style.SUCCESS(
                "\n✓ User groups setup completed successfully!"
            )
        )
        
        # Display group information
        self.stdout.write("\nConfigured groups:")
        for group in Group.objects.filter(name__in=[g['name'] for g in groups_config]):
            self.stdout.write(f"  • {group.name}")
