# Generated manually on 2026-02-12 12:10

from django.db import migrations, models
import logging

logger = logging.getLogger(__name__)


def remove_duplicate_htmlxml_records(apps, schema_editor):
    """
    Remove duplicate HTMLXML records, keeping only the most recently updated one.
    """
    HTMLXML = apps.get_model("htmlxml", "HTMLXML")
    db_alias = schema_editor.connection.alias
    
    # Find all migrated_articles that have duplicates
    from django.db.models import Count
    duplicates = (
        HTMLXML.objects.using(db_alias)
        .values("migrated_article")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )
    
    total_duplicates = 0
    for duplicate in duplicates:
        migrated_article_id = duplicate["migrated_article"]
        if migrated_article_id is None:
            continue
            
        # Get all records for this migrated_article ordered by most recent first
        records = HTMLXML.objects.using(db_alias).filter(
            migrated_article_id=migrated_article_id
        ).order_by("-updated")
        
        # Keep the first (most recent), delete the rest
        records_to_delete = list(records[1:])
        count = len(records_to_delete)
        
        if count > 0:
            total_duplicates += count
            logger.warning(
                f"Removing {count} duplicate HTMLXML record(s) for "
                f"migrated_article_id={migrated_article_id}"
            )
            for record in records_to_delete:
                record.delete()
    
    if total_duplicates > 0:
        logger.info(f"Removed {total_duplicates} duplicate HTMLXML records in total")
    else:
        logger.info("No duplicate HTMLXML records found")


def reverse_migration(apps, schema_editor):
    """
    Reverse migration does nothing - we can't restore deleted duplicates
    """
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("htmlxml", "0004_alter_bodyandbackfile_file_and_more"),
    ]

    operations = [
        # First, clean up existing duplicates
        migrations.RunPython(
            remove_duplicate_htmlxml_records,
            reverse_migration,
        ),
        # Then add the unique constraint
        migrations.AddConstraint(
            model_name="htmlxml",
            constraint=models.UniqueConstraint(
                fields=["migrated_article"],
                name="unique_migrated_article",
                # Allow multiple NULL values
                condition=models.Q(migrated_article__isnull=False),
            ),
        ),
    ]
