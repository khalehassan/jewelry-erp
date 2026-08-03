from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0006_jewelryitem_source_purchase_line"),
    ]

    operations = [
        migrations.AddField(
            model_name="jewelryitem",
            name="is_archived",
            field=models.BooleanField(
                default=False,
                editable=False,
                help_text=(
                    "Retained only as an audit reference after its source purchase is reversed."
                ),
            ),
        ),
        migrations.AddConstraint(
            model_name="jewelryitem",
            constraint=models.CheckConstraint(
                condition=models.Q(("is_archived", False), ("quantity", 0), _connector="OR"),
                name="archived_jewelry_item_has_zero_quantity",
            ),
        ),
    ]
