from decimal import Decimal

from django.db import models
from django.db.models import ProtectedError
from django.db.models.signals import post_save, post_delete, pre_delete
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
    journal_entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        who = self.supplier.name if self.supplier else "Cash purchase"
        return f"Purchase #{self.pk} — {who}"

    @property
    def total(self):
        return sum((line.line_total for line in self.lines.all()), Decimal("0.00"))

    def post_to_ledger(self):
        if self.journal_entry_id or not self.lines.exists():
            return
        from accounting.services import create_entry
        total = self.total
        payable = "2000" if self.on_credit else "1000"
        lines = [
            ("1200", total, Decimal("0.00")),
            (payable, Decimal("0.00"), total),
        ]
        entry = create_entry(self.created_at.date(), f"Purchase #{self.pk}", lines)
        self.journal_entry = entry
        self.save(update_fields=["journal_entry"])


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, related_name="lines", on_delete=models.CASCADE)
    barcode = models.CharField(max_length=50, blank=True, default="", help_text="Scan or type; leave blank to auto-generate")
    name = models.CharField(max_length=120, default="")
    category = models.CharField(max_length=20, choices=JewelryItem.Category.choices, default=JewelryItem.Category.RING)
    karat = models.IntegerField(choices=JewelryItem.Karat.choices, default=JewelryItem.Karat.K21)
    weight_grams = models.DecimalField(max_digits=8, decimal_places=3, default=0)
    stone_details = models.CharField(max_length=200, blank=True, default="")
    location = models.CharField(max_length=20, choices=JewelryItem.Location.choices, default=JewelryItem.Location.SAFE)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity = models.PositiveIntegerField(default=1)
    created_item = models.ForeignKey(JewelryItem, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_lines")

    def __str__(self):
        return f"{self.quantity} × {self.name}"

    @property
    def line_total(self):
        return self.unit_cost * self.quantity


@receiver(post_save, sender=PurchaseLine)
def create_stock_item(sender, instance, created, **kwargs):
    if created and instance.created_item_id is None:
        barcode = instance.barcode or None
        # If that barcode is already used, drop it so a unique one is auto-generated
        if barcode and JewelryItem.objects.filter(barcode=barcode).exists():
            barcode = None
        item = JewelryItem.objects.create(
            name=instance.name,
            barcode=barcode,
            category=instance.category,
            karat=instance.karat,
            weight_grams=instance.weight_grams,
            stone_details=instance.stone_details,
            location=instance.location,
            cost_price=instance.unit_cost,
            quantity=instance.quantity,
        )
        instance.created_item = item
        instance.save(update_fields=["created_item"])


@receiver(post_delete, sender=PurchaseLine)
def remove_item_on_line_delete(sender, instance, **kwargs):
    if instance.created_item_id:
        try:
            JewelryItem.objects.filter(pk=instance.created_item_id).delete()
        except ProtectedError:
            pass  # already sold — keep it


@receiver(pre_delete, sender=Purchase)
def cleanup_on_purchase_delete(sender, instance, **kwargs):
    # 1) delete the inventory pieces this purchase created
    item_ids = list(instance.lines.filter(created_item__isnull=False).values_list("created_item_id", flat=True))
    if item_ids:
        try:
            JewelryItem.objects.filter(pk__in=item_ids).delete()
        except ProtectedError:
            pass
    # 2) delete its journal entry (unlink first so it can't loop back)
    je_id = instance.journal_entry_id
    if je_id:
        Purchase.objects.filter(pk=instance.pk).update(journal_entry=None)
        from accounting.models import JournalEntry
        JournalEntry.objects.filter(pk=je_id).delete()