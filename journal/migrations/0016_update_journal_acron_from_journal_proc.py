from django.db import migrations


def update_journal_acron(apps, schema_editor):
    """
    Journal.journal_acron fica preenchido somente se o acrônimo é o mesmo
    em todas as coleções (JournalProc); caso contrário, fica vazio.
    """
    Journal = apps.get_model("journal", "Journal")
    JournalProc = apps.get_model("proc", "JournalProc")

    acrons_by_journal = {}
    for journal_id, acron in (
        JournalProc.objects.filter(journal__isnull=False, acron__isnull=False)
        .exclude(acron="")
        .values_list("journal_id", "acron")
        .iterator()
    ):
        acrons_by_journal.setdefault(journal_id, set()).add(acron)

    for journal_id, acrons in acrons_by_journal.items():
        journal_acron = acrons.pop() if len(acrons) == 1 else None
        Journal.objects.filter(id=journal_id).exclude(
            journal_acron=journal_acron
        ).update(journal_acron=journal_acron)


class Migration(migrations.Migration):

    dependencies = [
        ("journal", "0015_alter_officialjournal_next_journal_title"),
        ("proc", "0015_alter_articleproc_migration_status_and_more"),
    ]

    operations = [
        migrations.RunPython(update_journal_acron, migrations.RunPython.noop),
    ]
