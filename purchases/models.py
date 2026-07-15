from decimal import Decimal

from django.db import models
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from inventory.models import JewelryItem


class Supplier(models.Model):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Purchase(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="purchases")
    on_credit = models.BooleanField(default=False, help_text="Bought on credit (you owe the supplier)")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        who = self.supplier.name if self.supplier else "Cash purchase"
        return f"Purchase #{self.pk} — {who}"

    @property
    def total(self):
        return sum((line.line_total for line in self.lines.all()), Decimal("0.00"))


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, related_name="lines", on_delete=models.CASCADE)

    # Item details entered at purchase time (temporary defaults let the migration run cleanly)
    name = models.CharField(max_length=120, default="")
    category = models.CharField(max_length=20, choices=JewelryItem.Category.choices, default=JewelryItem.Category.RING)
    karat = models.IntegerField(choices=JewelryItem.Karat.choices, default=JewelryItem.Karat.K21)
    weight_grams = models.DecimalField(max_digits=8, decimal_places=3, default=0)
    stone_details = models.CharField(max_length=200, blank=True, default="")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity = models.PositiveIntegerField(default=1)

    created_item = models.ForeignKey(JewelryItem, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_lines")

    def __str__(self):
        return f"{self.quantity} × {self.name}"

    @property
    def line_total(self):
        return self.unit_cost * self.quantity


# --- Buying a piece CREATES it in inventory ---
@receiver(post_save, sender=PurchaseLine)
def create_stock_item(sender, instance, created, **kwargs):
    if created and instance.created_item_id is None:
        item = JewelryItem.objects.create(
            name=instance.name,
            category=instance.category,
            karat=instance.karat,
            weight_grams=instance.weight_grams,
            stone_details=instance.stone_details,
            cost_price=instance.unit_cost,
            quantity=instance.quantity,
        )
        instance.created_item = item
        instance.save(update_fields=["created_item"])


@receiver(post_delete, sender=PurchaseLine)
def reverse_stock_on_delete(sender, instance, **kwargs):
    if instance.created_item_id:
        item = instance.created_item
        item.quantity = item.quantity - instance.quantity
        item.save()