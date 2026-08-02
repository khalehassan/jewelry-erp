from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower, Trim
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from accounting.services import POSTED_LOCK_MESSAGE, deletion_origin_includes
from config.identity import normalize_party, validate_party_duplicates
from inventory.models import JewelryItem


class Supplier(models.Model):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower(Trim("name")),
                name="supplier_name_normalized_unique",
            ),
            models.UniqueConstraint(
                Trim("phone"),
                condition=~models.Q(phone=""),
                name="supplier_phone_normalized_unique",
            ),
            models.UniqueConstraint(
                Lower(Trim("email")),
                condition=~models.Q(email=""),
                name="supplier_email_normalized_unique",
            ),
        ]

    def clean(self):
        super().clean()
        normalize_party(self)
        validate_party_duplicates(self, "supplier")

    def save(self, *args, **kwargs):
        normalize_party(self)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Purchase(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="purchases")
    on_credit = models.BooleanField(default=False, help_text="Bought on credit (you owe the supplier)")
    is_opening = models.BooleanField(default=False, help_text="Stock you already owned, brought onto the books (e.g. a CSV import)")
    journal_entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.is_opening:
            return f"Opening stock #{self.pk}"
        who = self.supplier.name if self.supplier else "Cash purchase"
        return f"Purchase #{self.pk} — {who}"

    def save(self, *args, **kwargs):
        # Locked once posted; only the system's own journal_entry stamp gets through.
        if self.pk and self.journal_entry_id:
            if set(kwargs.get("update_fields") or []) != {"journal_entry"}:
                raise ValidationError(POSTED_LOCK_MESSAGE.format(what=f"Purchase #{self.pk}"))
        super().save(*args, **kwargs)

    @property
    def total(self):
        return sum((line.line_total for line in self.lines.all()), Decimal("0.00"))

    def post_to_ledger(self):
        if self.journal_entry_id:
            return
        if not self.lines.exists():
            raise ValidationError("A purchase must contain at least one item.")
        if self.total <= 0:
            raise ValidationError("Purchase total must be greater than zero.")
        from collections import defaultdict
        from accounting import mapping
        from accounting.services import create_entry

        # Stock lands in the finished-gold account matching each piece's karat.
        inventory_by = defaultdict(Decimal)
        for purchase_line in self.lines.all():
            inventory_by[mapping.gold_inventory(purchase_line.karat)] += purchase_line.line_total

        if self.is_opening:
            # Stock that existed before the books did. Standard practice is to park
            # the other side in Opening Balance Equity, then clear that one account
            # to Owner's Capital once every opening balance is entered.
            credit_account = mapping.OPENING_BALANCE_EQUITY
            description = f"Opening stock #{self.pk}"
        else:
            credit_account = mapping.SUPPLIER_PAYABLE if self.on_credit else mapping.CASH
            description = f"Purchase #{self.pk}"

        lines = [(code, amount, Decimal("0.00")) for code, amount in inventory_by.items()]
        lines.append((credit_account, Decimal("0.00"), self.total))
        entry = create_entry(self.created_at.date(), description, lines)
        self.journal_entry = entry
        self.save(update_fields=["journal_entry"])


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, related_name="lines", on_delete=models.CASCADE)
    barcode = models.CharField(max_length=50, blank=True, default="", help_text="Scan or type; leave blank to auto-generate")
    name = models.CharField(max_length=120, default="")
    category = models.CharField(max_length=20, choices=JewelryItem.Category.choices, default=JewelryItem.Category.RING)
    karat = models.IntegerField(choices=JewelryItem.Karat.choices, default=JewelryItem.Karat.K21)
    weight_grams = models.DecimalField(
        max_digits=8,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    stone_details = models.CharField(max_length=200, blank=True, default="")
    location = models.CharField(max_length=20, choices=JewelryItem.Location.choices, default=JewelryItem.Location.SAFE)
    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    created_item = models.ForeignKey(JewelryItem, null=True, blank=True, on_delete=models.RESTRICT, related_name="purchase_lines")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weight_grams__gt=0),
                name="purchase_line_weight_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_cost__gt=0),
                name="purchase_line_unit_cost_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="purchase_line_quantity_positive",
            ),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.name}"

    def _guard_posted(self, update_fields=None):
        # The created_item stamp is the signal linking this line to the stock it
        # made — a system write, not a user edit, so it stays allowed.
        if set(update_fields or []) == {"created_item"}:
            return
        if self.purchase_id and self.purchase.journal_entry_id:
            raise ValidationError(POSTED_LOCK_MESSAGE.format(what=f"Purchase #{self.purchase_id}"))

    def save(self, *args, **kwargs):
        self._guard_posted(kwargs.get("update_fields"))
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard_posted()
        super().delete(*args, **kwargs)

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
            source_purchase_line=instance,
        )
        instance.created_item = item
        instance.save(update_fields=["created_item"])


@receiver(pre_delete, sender=Purchase)
def cleanup_on_purchase_delete(sender, instance, origin=None, **kwargs):
    # The PurchaseLine -> JewelryItem ownership link handles stock deletion.
    # If a sale still references an item, Django blocks the entire purchase
    # deletion before anything is removed, preserving every connection.
    je_id = instance.journal_entry_id
    if je_id:
        from accounting.models import JournalEntry
        if deletion_origin_includes(origin, JournalEntry, je_id):
            return
        Purchase.objects.filter(pk=instance.pk).update(journal_entry=None)
        JournalEntry.objects.filter(pk=je_id).delete()
