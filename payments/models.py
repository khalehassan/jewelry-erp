from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from accounting.services import POSTED_LOCK_MESSAGE, deletion_origin_includes


class Payment(models.Model):
    class Kind(models.TextChoices):
        RECEIVE = "receive", "Received from customer"
        PAY = "pay", "Paid to supplier"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    supplier = models.ForeignKey("purchases.Supplier", on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    note = models.CharField(max_length=200, blank=True)
    journal_entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="payment_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind="receive",
                        customer__isnull=False,
                        supplier__isnull=True,
                    )
                    | models.Q(
                        kind="pay",
                        customer__isnull=True,
                        supplier__isnull=False,
                    )
                ),
                name="payment_party_matches_kind",
            ),
        ]

    def __str__(self):
        who = self.customer.name if self.customer else (self.supplier.name if self.supplier else "—")
        verb = "from" if self.kind == self.Kind.RECEIVE else "to"
        return f"Payment #{self.pk} — {self.amount} {verb} {who}"

    @classmethod
    def customer_balance(cls, customer, exclude_payment_id=None):
        """Return credit sales, receipts, and the customer's unpaid balance."""
        billed = sum(
            (
                sale.total
                for sale in customer.sales.filter(
                    on_credit=True,
                    status="posted",
                )
            ),
            Decimal("0.00"),
        )
        receipts = customer.payments.filter(kind=cls.Kind.RECEIVE)
        if exclude_payment_id:
            receipts = receipts.exclude(pk=exclude_payment_id)
        paid = sum((payment.amount for payment in receipts), Decimal("0.00"))
        return billed, paid, billed - paid

    @classmethod
    def supplier_balance(cls, supplier, exclude_payment_id=None):
        """Return credit purchases, payments, and the unpaid supplier balance."""
        billed = sum(
            (
                purchase.total
                for purchase in supplier.purchases.filter(
                    on_credit=True,
                    status="posted",
                )
            ),
            Decimal("0.00"),
        )
        payments = supplier.payments.filter(kind=cls.Kind.PAY)
        if exclude_payment_id:
            payments = payments.exclude(pk=exclude_payment_id)
        paid = sum((payment.amount for payment in payments), Decimal("0.00"))
        return billed, paid, billed - paid

    def clean(self):
        super().clean()
        errors = {}

        if self.kind == self.Kind.RECEIVE:
            if not self.customer_id:
                errors["customer"] = "Choose the customer who is paying."
            if self.supplier_id:
                errors["supplier"] = "A customer receipt cannot also name a supplier."
            customer = None
            if self.customer_id:
                from customers.models import Customer
                customer = Customer.objects.filter(pk=self.customer_id).first()
            if customer is not None and self.amount is not None and self.amount > 0:
                _, _, outstanding = self.customer_balance(customer, self.pk)
                if self.amount > outstanding:
                    errors["amount"] = (
                        f"Payment exceeds {customer.name}'s outstanding balance of "
                        f"{outstanding:,.2f} EGP."
                    )

        elif self.kind == self.Kind.PAY:
            if not self.supplier_id:
                errors["supplier"] = "Choose the supplier being paid."
            if self.customer_id:
                errors["customer"] = "A supplier payment cannot also name a customer."
            supplier = None
            if self.supplier_id:
                from purchases.models import Supplier
                supplier = Supplier.objects.filter(pk=self.supplier_id).first()
            if supplier is not None and self.amount is not None and self.amount > 0:
                _, _, outstanding = self.supplier_balance(supplier, self.pk)
                if self.amount > outstanding:
                    errors["amount"] = (
                        f"Payment exceeds {supplier.name}'s outstanding balance of "
                        f"{outstanding:,.2f} EGP."
                    )

        if errors:
            raise ValidationError(errors)

    def _lock_party(self):
        if self.kind == self.Kind.RECEIVE and self.customer_id:
            from customers.models import Customer
            Customer.objects.select_for_update().filter(pk=self.customer_id).exists()
        elif self.kind == self.Kind.PAY and self.supplier_id:
            from purchases.models import Supplier
            Supplier.objects.select_for_update().filter(pk=self.supplier_id).exists()

    def save(self, *args, **kwargs):
        # Locked once posted; only the system's own journal_entry stamp gets through.
        if self.pk and self.journal_entry_id:
            if set(kwargs.get("update_fields") or []) != {"journal_entry"}:
                raise ValidationError(POSTED_LOCK_MESSAGE.format(what=f"Payment #{self.pk}"))
        with transaction.atomic():
            self._lock_party()
            self.full_clean()
            super().save(*args, **kwargs)

    def post_to_ledger(self):
        if self.journal_entry_id:
            return
        from accounting import mapping
        from accounting.services import create_entry
        with transaction.atomic():
            self._lock_party()
            self.full_clean()
            amount = self.amount
            if self.kind == self.Kind.RECEIVE:
                # Money in: Cash goes up, the customer owes us less
                who = self.customer.name
                lines = [
                    (mapping.CASH, amount, Decimal("0.00")),
                    (mapping.RETAIL_RECEIVABLE, Decimal("0.00"), amount),
                ]
                description = f"Payment #{self.pk} received from {who}"
            else:
                # Money out: we owe the supplier less, Cash goes down
                who = self.supplier.name
                lines = [
                    (mapping.SUPPLIER_PAYABLE, amount, Decimal("0.00")),
                    (mapping.CASH, Decimal("0.00"), amount),
                ]
                description = f"Payment #{self.pk} paid to {who}"

            entry = create_entry(self.created_at.date(), description, lines)
            self.journal_entry = entry
            self.save(update_fields=["journal_entry"])


@receiver(pre_delete, sender=Payment)
def cleanup_on_payment_delete(sender, instance, origin=None, **kwargs):
    je_id = instance.journal_entry_id
    if je_id:
        from accounting.models import JournalEntry
        if deletion_origin_includes(origin, JournalEntry, je_id):
            return
        Payment.objects.filter(pk=instance.pk).update(journal_entry=None)
        JournalEntry.objects.filter(pk=je_id).delete()
