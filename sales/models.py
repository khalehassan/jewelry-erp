from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver
from django.utils import timezone

from accounting.services import POSTED_LOCK_MESSAGE, deletion_origin_includes
from inventory.models import JewelryItem


class Sale(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        POSTED = "posted", "Posted"
        REVERSED = "reversed", "Reversed"

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, null=True, blank=True, related_name="sales")
    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    on_credit = models.BooleanField(default=False, help_text="Sold on credit (customer owes you)")
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
        related_name="reversed_sales",
        editable=False,
    )
    reversal_reason = models.TextField(blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(discount__gte=0),
                name="sale_discount_nonnegative",
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
                name="sale_status_consistent",
            ),
        ]

    def __str__(self):
        who = self.customer.name if self.customer else "Walk-in customer"
        return f"Sale #{self.pk} — {who}"

    def save(self, *args, **kwargs):
        # The first ledger stamp is allowed; after that, history is immutable.
        if self.pk:
            existing = Sale.objects.filter(pk=self.pk).values("journal_entry_id").first()
            if existing and existing["journal_entry_id"]:
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
        if self.status == self.Status.REVERSED:
            raise ValidationError(f"Sale #{self.pk} is reversed and cannot be posted again.")
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
        self.status = self.Status.POSTED
        self.save(update_fields=["journal_entry", "status"])

    def reverse(self, *, user, reason):
        """Reverse a posted sale and return its quantities to inventory."""
        reason = " ".join(str(reason or "").split())
        if not reason:
            raise ValidationError("A reversal reason is required.")
        if not self.pk:
            raise ValidationError("Save and post the sale before reversing it.")
        if user is None or not getattr(user, "pk", None):
            raise ValidationError("A named user is required to reverse a sale.")

        from accounting.services import create_entry
        from payments.models import Payment

        with transaction.atomic():
            sale = (
                Sale.objects.select_for_update()
                .select_related("journal_entry", "customer")
                .get(pk=self.pk)
            )
            if sale.status == self.Status.REVERSED:
                raise ValidationError(f"Sale #{sale.pk} has already been reversed.")
            if sale.status != self.Status.POSTED or not sale.journal_entry_id:
                raise ValidationError("Only a posted sale can be reversed.")

            sale_lines = list(sale.lines.order_by("pk"))
            if not sale_lines:
                raise ValidationError("This sale has no item lines to reverse.")
            item_ids = [line.item_id for line in sale_lines]
            items = {
                item.pk: item
                for item in JewelryItem.objects.select_for_update().filter(pk__in=item_ids)
            }
            if len(items) != len(set(item_ids)):
                raise ValidationError(
                    "One of this sale's inventory items no longer exists. Reversal was cancelled."
                )

            if sale.on_credit and sale.customer_id:
                _, _, outstanding = Payment.customer_balance(sale.customer)
                if outstanding < sale.total:
                    raise ValidationError(
                        "This credit sale cannot be reversed because a customer receipt "
                        "has already been applied against it."
                    )

            original_lines = list(
                sale.journal_entry.lines.select_related("account").order_by("pk")
            )
            if not original_lines or not sale.journal_entry.is_balanced:
                raise ValidationError(
                    "The original journal entry is incomplete or unbalanced. Reversal was cancelled."
                )
            reversing_lines = [
                (line.account.code, line.credit, line.debit)
                for line in original_lines
            ]
            reversal_entry = create_entry(
                timezone.localdate(),
                f"Reversal of Sale #{sale.pk}: {reason}"[:255],
                reversing_lines,
            )

            for line in sale_lines:
                updated = JewelryItem.objects.filter(pk=line.item_id).update(
                    quantity=F("quantity") + line.quantity,
                )
                if updated != 1:
                    raise ValidationError(
                        f"Inventory for sale line #{line.pk} changed during reversal. Try again."
                    )

            reversed_at = timezone.now()
            updated = Sale.objects.filter(
                pk=sale.pk,
                status=self.Status.POSTED,
            ).update(
                status=self.Status.REVERSED,
                reversal_journal_entry=reversal_entry,
                reversed_at=reversed_at,
                reversed_by=user,
                reversal_reason=reason,
            )
            if updated != 1:
                raise ValidationError("The sale status changed during reversal. Try again.")

        self.refresh_from_db()
        return reversal_entry


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
    if instance.status == Sale.Status.REVERSED:
        raise ValidationError("A reversed sale is a permanent audit record and cannot be deleted.")
    je_id = instance.journal_entry_id
    if je_id:
        from accounting.models import JournalEntry
        if deletion_origin_includes(origin, JournalEntry, je_id):
            return
        Sale.objects.filter(pk=instance.pk).update(journal_entry=None)
        JournalEntry.objects.filter(pk=je_id).delete()
