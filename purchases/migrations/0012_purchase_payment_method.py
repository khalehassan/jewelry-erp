from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0006_other_payment_account"),
        ("purchases", "0011_purchase_reversal"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchase",
            name="payment_method",
            field=models.CharField(
                choices=[
                    ("cash", "Cash"),
                    ("bank", "Bank"),
                    ("other", "Other"),
                ],
                default="cash",
                help_text=(
                    "Used for purchases paid immediately; credit purchases post to Supplier Payable."
                ),
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="purchase",
            constraint=models.CheckConstraint(
                condition=models.Q(("payment_method__in", ("cash", "bank", "other"))),
                name="purchase_payment_method_valid",
            ),
        ),
    ]
