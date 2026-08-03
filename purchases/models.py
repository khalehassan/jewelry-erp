from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models.functions import Lower, Trim
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone

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
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        POSTED = "posted", "Posted"
        REVERSED = "reversed", "Reversed"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        BANK = "bank", "Bank"
        OTHER = "other", "Other"

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="purchases")
    on_credit = models.BooleanField(default=False, help_text="Bought on credit (you owe the supplier)")
    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
        help_text="Used for purchases paid immediately; credit purchases post to Supplier Payable.",
    )
    is_opening = models.BooleanField(default=False, help_text="Stock you already owned, brought onto the books (e.g. a CSV import)")
    journal_entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    reversal_journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    reversed_at = models.DateTimeField(null=True, blank=True, editable=False)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversed_purchases",
        editable=False,
    )
    reversal_reason = models.TextField(blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(payment_method__in=("cash", "bank", "other")),
                name="purchase_payment_method_valid",
            ),
            models.CheckConstraint(
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
        ]

    def __str__(self):
        if self.is_opening:
            return f"Opening stock #{self.pk}"
        if self.supplier:
            who = self.supplier.name
        elif self.on_credit:
            who = "Credit purchase"
        else:
            who = f"{self.get_payment_method_display()} purchase"
        return f"Purchase #{self.pk} — {who}"

    def save(self, *args, **kwargs):
        # The first ledger stamp is allowed; after that, history is immutable.
        if self.pk:
            existing = Purchase.objects.filter(pk=self.pk).values("journal_entry_id").first()
            if existing and existing["journal_entry_id"]:
                raise ValidationError(POSTED_LOCK_MESSAGE.format(what=f"Purchase #{self.pk}"))
        super().save(*args, **kwargs)

    @property
    def total(self):
        return sum((line.line_total for line in self.lines.all()), Decimal("0.00"))

    def post_to_ledger(self):
        if self.status == self.Status.REVERSED:
            raise ValidationError(f"Purchase #{self.pk} is reversed and cannot be posted again.")
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
            payment_accounts = {
                self.PaymentMethod.CASH: mapping.CASH,
                self.PaymentMethod.BANK: mapping.BANK,
                self.PaymentMethod.OTHER: mapping.OTHER_PAYMENT,
            }
            if self.on_credit:
                credit_account = mapping.SUPPLIER_PAYABLE
                payment_label = "On credit"
            else:
                credit_account = payment_accounts[self.payment_method]
                payment_label = self.get_payment_method_display()
            description = f"Purchase #{self.pk} ({payment_label})"

        lines = [(code, amount, Decimal("0.00")) for code, amount in inventory_by.items()]
        lines.append((credit_account, Decimal("0.00"), self.total))
        entry = create_entry(self.created_at.date(), description, lines)
        self.journal_entry = entry
        self.status = self.Status.POSTED
        self.save(update_fields=["journal_entry", "status"])

    def reverse(self, *, user, reason):
        """Reverse a posted purchase while preserving its complete audit trail."""
        reason = " ".join(str(reason or "").split())
        if not reason:
            raise ValidationError("A reversal reason is required.")
        if not self.pk:
            raise ValidationError("Save and post the purchase before reversing it.")
        if user is None or not getattr(user, "pk", None):
            raise ValidationError("A named user is required to reverse a purchase.")

        from accounting.services import create_entry
        from payments.models import Payment
        from sales.models import Sale, SaleLine

        with transaction.atomic():
            purchase = (
                Purchase.objects.select_for_update()
                .select_related("journal_entry", "supplier")
                .get(pk=self.pk)
            )
            if purchase.status == self.Status.REVERSED:
                raise ValidationError(f"Purchase #{purchase.pk} has already been reversed.")
            if purchase.status != self.Status.POSTED or not purchase.journal_entry_id:
                raise ValidationError("Only a posted purchase can be reversed.")

            purchase_lines = list(purchase.lines.order_by("pk"))
            if not purchase_lines:
                raise ValidationError("This purchase has no item lines to reverse.")

            item_ids = [line.created_item_id for line in purchase_lines]
            if any(item_id is None for item_id in item_ids):
                raise ValidationError(
                    "This purchase is missing its inventory link and cannot be reversed safely."
                )
            items = {
                item.pk: item
                for item in JewelryItem.objects.select_for_update().filter(pk__in=item_ids)
            }
            if len(items) != len(set(item_ids)):
                raise ValidationError(
                    "One of this purchase's inventory items no longer exists. Reversal was cancelled."
                )

            linked_sale_lines = SaleLine.objects.filter(item_id__in=item_ids)
            if linked_sale_lines.exclude(sale__status=Sale.Status.REVERSED).exists():
                raise ValidationError(
                    "This purchase cannot be reversed because at least one purchased item "
                    "is still used on an active sale. Reverse that sale first."
                )
            historical_item_ids = set(
                linked_sale_lines.filter(sale__status=Sale.Status.REVERSED)
                .values_list("item_id", flat=True)
            )

            for line in purchase_lines:
                item = items[line.created_item_id]
                if (
                    item.source_purchase_line_id != line.pk
                    or item.quantity != line.quantity
                    or item.is_archived
                ):
                    raise ValidationError(
                        f"Inventory for {line.name} no longer matches the original purchase. "
                        "Reversal was cancelled."
                    )

            if purchase.on_credit and purchase.supplier_id:
                _, _, outstanding = Payment.supplier_balance(purchase.supplier)
                if outstanding < purchase.total:
                    raise ValidationError(
                        "This credit purchase cannot be reversed because a supplier payment "
                        "has already been applied against it."
                    )

            original_lines = list(
                purchase.journal_entry.lines.select_related("account").order_by("pk")
            )
            if not original_lines or not purchase.journal_entry.is_balanced:
                raise ValidationError(
                    "The original journal entry is incomplete or unbalanced. Reversal was cancelled."
                )
            reversing_lines = [
                (line.account.code, line.credit, line.debit)
                for line in original_lines
            ]
            reversal_entry = create_entry(
                timezone.localdate(),
                f"Reversal of Purchase #{purchase.pk}: {reason}"[:255],
                reversing_lines,
            )

            for line in purchase_lines:
                item = items[line.created_item_id]
                if item.pk in historical_item_ids:
                    # The reversed sale line is a permanent audit record and still
                    # references this item. Keep the reference, but remove it from
                    # all usable and valued inventory.
                    updated_item = JewelryItem.objects.filter(
                        pk=item.pk,
                        is_archived=False,
                        quantity=line.quantity,
                    ).update(quantity=0, is_archived=True)
                    if updated_item != 1:
                        raise ValidationError(
                            f"Inventory for {line.name} changed during reversal. Try again."
                        )
                else:
                    line.created_item = None
                    line.save(update_fields=["created_item"])
                    item.delete()

            reversed_at = timezone.now()
            updated = Purchase.objects.filter(
                pk=purchase.pk,
                status=self.Status.POSTED,
            ).update(
                status=self.Status.REVERSED,
                reversal_journal_entry=reversal_entry,
                reversed_at=reversed_at,
                reversed_by=user,
                reversal_reason=reason,
            )
            if updated != 1:
                raise ValidationError("The purchase status changed during reversal. Try again.")

        self.refresh_from_db()
        return reversal_entry


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
    raw_gold_price_per_gram = models.DecimalField(
        "raw gold price/g",
        max_digits=18,
        decimal_places=9,
        default=0,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    craftsmanship_per_gram = models.DecimalField(
        "craftsmanship/g",
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    stamp_charge = models.DecimalField(
        "stamp/piece",
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.00"))],
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
                condition=models.Q(raw_gold_price_per_gram__gt=0),
                name="purchase_line_raw_gold_price_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(craftsmanship_per_gram__gte=0),
                name="purchase_line_craftsmanship_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(stamp_charge__gte=0),
                name="purchase_line_stamp_nonnegative",
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
    def cost_per_piece(self):
        amount = (
            self.weight_grams
            * (self.raw_gold_price_per_gram + self.craftsmanship_per_gram)
            + self.stamp_charge
        )
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def line_total(self):
        return self.cost_per_piece * self.quantity


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
            cost_price=instance.cost_per_piece,
            quantity=instance.quantity,
            source_purchase_line=instance,
        )
        instance.created_item = item
        instance.save(update_fields=["created_item"])


@receiver(pre_delete, sender=Purchase)
def cleanup_on_purchase_delete(sender, instance, origin=None, **kwargs):
    if instance.status == Purchase.Status.REVERSED:
        raise ValidationError("A reversed purchase is a permanent audit record and cannot be deleted.")
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
