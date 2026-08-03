from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def mark_existing_purchases(apps, schema_editor):
    Purchase = apps.get_model("purchases", "Purchase")
    Purchase.objects.filter(journal_entry__isnull=False).update(status="posted")


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("purchases", "0010_purchase_cost_components"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchase",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("posted", "Posted"),
                    ("reversed", "Reversed"),
                ],
                default="draft",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="purchase",
            name="reversal_journal_entry",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="accounting.journalentry",
            ),
        ),
        migrations.AddField(
            model_name="purchase",
            name="reversal_reason",
            field=models.TextField(blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="purchase",
            name="reversed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="purchase",
            name="reversed_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reversed_purchases",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(mark_existing_purchases, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="purchase",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        status="draft",
                        journal_entry__isnull=True,
                        reversal_journal_entry__isnull=True,
                        reversed_at__isnull=True,
                        reversed_by__isnull=True,
                        reversal_reason="",
                    )
                    | models.Q(
                        status="posted",
                        journal_entry__isnull=False,
                        reversal_journal_entry__isnull=True,
                        reversed_at__isnull=True,
                        reversed_by__isnull=True,
                        reversal_reason="",
                    )
                    | (
                        models.Q(
                            status="reversed",
                            journal_entry__isnull=False,
                            reversal_journal_entry__isnull=False,
                            reversed_at__isnull=False,
                            reversed_by__isnull=False,
                        )
                        & ~models.Q(reversal_reason="")
                    )
                ),
                name="purchase_status_consistent",
            ),
        ),
    ]
