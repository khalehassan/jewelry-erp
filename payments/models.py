from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from accounting.services import POSTED_LOCK_MESSAGE


class Payment(models.Model):
    class Kind(models.TextChoices):
        RECEIVE = "receive", "Received from customer"
        PAY = "pay", "Paid to supplier"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    supplier = models.ForeignKey("purchases.Supplier", on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=200, blank=True)
    journal_entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        who = self.customer.name if self.customer else (self.supplier.name if self.supplier else "—")
        verb = "from" if self.kind == self.Kind.RECEIVE else "to"
        return f"Payment #{self.pk} — {self.amount} {verb} {who}"

    def save(self, *args, **kwargs):
        # Locked once posted; only the system's own journal_entry stamp gets through.
        if self.pk and self.journal_entry_id:
            if set(kwargs.get("update_fields") or []) != {"journal_entry"}:
                raise ValidationError(POSTED_LOCK_MESSAGE.format(what=f"Payment #{self.pk}"))
        super().save(*args, **kwargs)

    def post_to_ledger(self):
        if self.journal_entry_id:
            return
        from accounting import mapping
        from accounting.services import create_entry
        amount = self.amount
        if self.kind == self.Kind.RECEIVE:
            # Money in: Cash goes up, the customer owes us less
            who = self.customer.name if self.customer else "customer"
            lines = [
                (mapping.CASH, amount, Decimal("0.00")),
                (mapping.RETAIL_RECEIVABLE, Decimal("0.00"), amount),
            ]
            description = f"Payment #{self.pk} received from {who}"
        else:
            # Money out: we owe the supplier less, Cash goes down
            who = self.supplier.name if self.supplier else "supplier"
            lines = [
                (mapping.SUPPLIER_PAYABLE, amount, Decimal("0.00")),
                (mapping.CASH, Decimal("0.00"), amount),
            ]
            description = f"Payment #{self.pk} paid to {who}"

        entry = create_entry(self.created_at.date(), description, lines)
        self.journal_entry = entry
        self.save(update_fields=["journal_entry"])


@receiver(pre_delete, sender=Payment)
def cleanup_on_payment_delete(sender, instance, **kwargs):
    je_id = instance.journal_entry_id
    if je_id:
        Payment.objects.filter(pk=instance.pk).update(journal_entry=None)
        from accounting.models import JournalEntry
        JournalEntry.objects.filter(pk=je_id).delete()
