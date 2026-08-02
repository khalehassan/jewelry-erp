from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from accounting.services import POSTED_LOCK_MESSAGE, deletion_origin_includes
from inventory.models import JewelryItem


class Sale(models.Model):
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, null=True, blank=True, related_name="sales")
    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    on_credit = models.BooleanField(default=False, help_text="Sold on credit (customer owes you)")
    journal_entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(discount__gte=0),
                name="sale_discount_nonnegative",
            ),
        ]

    def __str__(self):
        who = self.customer.name if self.customer else "Walk-in customer"
        return f"Sale #{self.pk} — {who}"

    def save(self, *args, **kwargs):
        # Once a sale is on the books it is locked. The only write still allowed
        # is the system stamping on its own journal_entry link.
        if self.pk and self.journal_entry_id:
            if set(kwargs.get("update_fields") or []) != {"journal_entry"}:
                raise ValidationError(POSTED_LOCK_MESSAGE.format(what=f"Sale #{self.pk}"))
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def subtotal(self):
        return sum((line.line_total for line in self.lines.all()), Decimal("0.00"))

    @property
    def total(self):
        return self.subtotal - self.discount

    def post_to_ledger(self):
        if self.journal_entry_id:
            return
        sale_lines = list(self.lines.select_related("item"))
        if not sale_lines:
            raise ValidationError("A sale must contain at least one item.")
        if len({line.item_id for line in sale_lines}) != len(sale_lines):
            raise ValidationError("The same inventory item cannot appear more than once in a sale.")
        for sale_line in sale_lines:
            sale_line.full_clean()
            if sale_line.line_total <= 0:
                raise ValidationError("Every sale line must have a total greater than zero.")
        if self.total <= 0:
            raise ValidationError("Sale total must be greater than zero. Reduce the discount.")
        from collections import defaultdict
        from accounting import mapping
        from accounting.services import create_entry

        # Revenue is recorded gross, with any discount shown as its own debit,
        # so the income statement can present discounts as a deduction.
        revenue_by = defaultdict(Decimal)
        cogs_by = defaultdict(Decimal)
        inventory_by = defaultdict(Decimal)
        for sale_line in sale_lines:
            karat = sale_line.item.karat
            revenue_by[mapping.gold_revenue(karat)] += sale_line.line_total
            cost = sale_line.item.cost_price * sale_line.quantity
            cogs_by[mapping.gold_cogs(karat)] += cost
            inventory_by[mapping.gold_inventory(karat)] += cost

        money_account = mapping.RETAIL_RECEIVABLE if self.on_credit else mapping.CASH
        lines = [(money_account, self.total, Decimal("0.00"))]
        if self.discount > 0:
            lines.append((mapping.SALES_DISCOUNTS, self.discount, Decimal("0.00")))
        lines += [(code, Decimal("0.00"), amount) for code, amount in revenue_by.items()]
        lines += [(code, amount, Decimal("0.00")) for code, amount in cogs_by.items()]
        lines += [(code, Decimal("0.00"), amount) for code, amount in inventory_by.items()]

        entry = create_entry(self.created_at.date(), f"Sale #{self.pk}", lines)
        self.journal_entry = entry
        self.save(update_fields=["journal_entry"])


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, related_name="lines", on_delete=models.CASCADE)
    item = models.ForeignKey(JewelryItem, on_delete=models.RESTRICT)
    gold_price_per_gram = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    making_charge_per_gram = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(gold_price_per_gram__gt=0),
                name="sale_line_gold_price_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(making_charge_per_gram__gte=0),
                name="sale_line_making_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="sale_line_quantity_positive",
            ),
            models.UniqueConstraint(
                fields=("sale", "item"),
                name="sale_line_item_unique",
                violation_error_message="The same inventory item cannot appear more than once in a sale.",
            ),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.item.name}"

    def _guard_posted(self):
        if self.sale_id and self.sale.journal_entry_id:
            raise ValidationError(POSTED_LOCK_MESSAGE.format(what=f"Sale #{self.sale_id}"))

    @staticmethod
    def _reserve_stock(item_id, quantity):
        updated = JewelryItem.objects.filter(
            pk=item_id,
            quantity__gte=quantity,
        ).update(quantity=F("quantity") - quantity)
        if updated:
            return
        item = JewelryItem.objects.filter(pk=item_id).only("name", "quantity").first()
        if item is None:
            raise ValidationError({"item": "The selected inventory item no longer exists."})
        raise ValidationError({
            "quantity": f"Not enough stock for {item.name}: only {item.quantity} available.",
        })

    def save(self, *args, **kwargs):
        self._guard_posted()
        with transaction.atomic():
            self.full_clean()
            if self._state.adding:
                self._reserve_stock(self.item_id, self.quantity)
            else:
                previous = SaleLine.objects.select_for_update().get(pk=self.pk)
                if previous.item_id == self.item_id:
                    difference = self.quantity - previous.quantity
                    if difference > 0:
                        self._reserve_stock(self.item_id, difference)
                    elif difference < 0:
                        JewelryItem.objects.filter(pk=self.item_id).update(
                            quantity=F("quantity") - difference,
                        )
                else:
                    JewelryItem.objects.filter(pk=previous.item_id).update(
                        quantity=F("quantity") + previous.quantity,
                    )
                    self._reserve_stock(self.item_id, self.quantity)
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard_posted()
        super().delete(*args, **kwargs)

    @property
    def line_total(self):
        price_per_piece = self.item.weight_grams * (self.gold_price_per_gram + self.making_charge_per_gram)
        return price_per_piece * self.quantity


@receiver(post_delete, sender=SaleLine)
def restore_stock_on_delete(sender, instance, **kwargs):
    if instance.item_id:
        JewelryItem.objects.filter(pk=instance.item_id).update(
            quantity=F("quantity") + instance.quantity,
        )


@receiver(pre_delete, sender=Sale)
def cleanup_on_sale_delete(sender, instance, origin=None, **kwargs):
    je_id = instance.journal_entry_id
    if je_id:
        from accounting.models import JournalEntry
        if deletion_origin_includes(origin, JournalEntry, je_id):
            return
        Sale.objects.filter(pk=instance.pk).update(journal_entry=None)
        JournalEntry.objects.filter(pk=je_id).delete()
