from decimal import Decimal

from django.db import models

from inventory.models import JewelryItem


class Sale(models.Model):
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales",
    )
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        who = self.customer.name if self.customer else "Walk-in customer"
        return f"Sale #{self.pk} — {who}"

    @property
    def subtotal(self):
        return sum((line.line_total for line in self.lines.all()), Decimal("0.00"))

    @property
    def total(self):
        return self.subtotal - self.discount


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, related_name="lines", on_delete=models.CASCADE)
    item = models.ForeignKey(JewelryItem, on_delete=models.PROTECT)
    gold_price_per_gram = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.quantity} × {self.item.name}"

    @property
    def line_total(self):
        price_per_piece = self.item.weight_grams * (self.gold_price_per_gram + self.item.making_charge_per_gram)
        return price_per_piece * self.quantity