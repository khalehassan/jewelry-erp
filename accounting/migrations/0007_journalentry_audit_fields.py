import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounting", "0006_other_payment_account"),
    ]

    operations = [
        migrations.AddField(
            model_name="journalentry",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="journal_entries_created",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="journalentry",
            name="source",
            field=models.CharField(
                choices=[("automated", "Automated"), ("manual", "Manual")],
                default="automated",
                editable=False,
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="journalentry",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("source", "automated"))
                    | models.Q(("created_by__isnull", False), ("source", "manual"))
                ),
                name="journal_entry_source_has_creator",
            ),
        ),
    ]
