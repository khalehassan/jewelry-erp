from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0006_other_payment_account"),
        ("sales", "0007_sale_reversal"),
    ]

    operations = [
        migrations.AddField(
            model_name="sale",
            name="payment_method",
            field=models.CharField(
                choices=[
                    ("cash", "Cash"),
                    ("bank", "Bank"),
                    ("other", "Other"),
                ],
                default="cash",
                help_text=(
                    "Used for sales paid immediately; credit sales post to Customer Receivables."
                ),
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="sale",
            constraint=models.CheckConstraint(
                condition=models.Q(("payment_method__in", ("cash", "bank", "other"))),
                name="sale_payment_method_valid",
            ),
        ),
    ]
