from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

import django.core.validators
from django.db import migrations, models


def split_legacy_unit_cost(apps, schema_editor):
    PurchaseLine = apps.get_model("purchases", "PurchaseLine")
    cent = Decimal("0.01")
    precision = Decimal("0.000000001")

    for line in PurchaseLine.objects.all().iterator():
        unit_cost = Decimal(line.unit_cost)
        weight = Decimal(line.weight_grams)
        raw_gold_price = (unit_cost / weight).quantize(precision, rounding=ROUND_DOWN)
        if raw_gold_price <= 0:
            raw_gold_price = precision

        raw_gold_value = (weight * raw_gold_price).quantize(
            cent,
            rounding=ROUND_HALF_UP,
        )
        stamp_charge = unit_cost - raw_gold_value
        if stamp_charge < 0:
            # This can only occur at the extreme edge of the field ranges. Keeping
            # the old total as stamp preserves every historical purchase exactly.
            raw_gold_price = precision
            stamp_charge = unit_cost

        PurchaseLine.objects.filter(pk=line.pk).update(
            raw_gold_price_per_gram=raw_gold_price,
            craftsmanship_per_gram=Decimal("0.00"),
            stamp_charge=stamp_charge,
        )


def restore_legacy_unit_cost(apps, schema_editor):
    PurchaseLine = apps.get_model("purchases", "PurchaseLine")
    cent = Decimal("0.01")

    for line in PurchaseLine.objects.all().iterator():
        unit_cost = (
            Decimal(line.weight_grams)
            * (
                Decimal(line.raw_gold_price_per_gram)
                + Decimal(line.craftsmanship_per_gram)
            )
            + Decimal(line.stamp_charge)
        ).quantize(cent, rounding=ROUND_HALF_UP)
        PurchaseLine.objects.filter(pk=line.pk).update(unit_cost=unit_cost)


class Migration(migrations.Migration):

    dependencies = [
        ("purchases", "0009_alter_purchaseline_quantity_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="purchaseline",
            name="purchase_line_unit_cost_positive",
        ),
        migrations.AddField(
            model_name="purchaseline",
            name="raw_gold_price_per_gram",
            field=models.DecimalField(
                decimal_places=9,
                default=0,
                max_digits=18,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.01")),
                ],
                verbose_name="raw gold price/g",
            ),
        ),
        migrations.AddField(
            model_name="purchaseline",
            name="craftsmanship_per_gram",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=12,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.00")),
                ],
                verbose_name="craftsmanship/g",
            ),
        ),
        migrations.AddField(
            model_name="purchaseline",
            name="stamp_charge",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=12,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.00")),
                ],
                verbose_name="stamp/piece",
            ),
        ),
        migrations.RunPython(split_legacy_unit_cost, restore_legacy_unit_cost),
        migrations.RemoveField(
            model_name="purchaseline",
            name="unit_cost",
        ),
        migrations.AddConstraint(
            model_name="purchaseline",
            constraint=models.CheckConstraint(
                condition=models.Q(raw_gold_price_per_gram__gt=0),
                name="purchase_line_raw_gold_price_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="purchaseline",
            constraint=models.CheckConstraint(
                condition=models.Q(craftsmanship_per_gram__gte=0),
                name="purchase_line_craftsmanship_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="purchaseline",
            constraint=models.CheckConstraint(
                condition=models.Q(stamp_charge__gte=0),
                name="purchase_line_stamp_nonnegative",
            ),
        ),
    ]
