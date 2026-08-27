from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("team", "0006_normalize_active_members"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="journalcompanycontract",
            constraint=models.CheckConstraint(
                condition=(
                    Q(start_date__isnull=True)
                    | Q(end_date__isnull=True)
                    | Q(start_date__lte=models.F("end_date"))
                ),
                name="team_contract_valid_date_range",
            ),
        ),
    ]
