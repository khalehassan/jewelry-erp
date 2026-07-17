from decimal import Decimal

from django.db import models
from django.db.models import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone


class Account(models.Model):
    class Type(models.TextChoices):
        ASSET = "asset", "Asset"
        LIABILITY = "liability", "Liability"
        EQUITY = "equity", "Equity"
        REVENUE = "revenue", "Revenue"
        EXPENSE = "expense", "Expense"

    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=20, choices=Type.choices)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.name}"

    @property
    def balance(self):
        totals = self.lines.aggregate(d=models.Sum("debit"), c=models.Sum("credit"))
        debit = totals["d"] or Decimal("0.00")
        credit = totals["c"] or Decimal("0.00")
        if self.type in (self.Type.ASSET, self.Type.EXPENSE):
            return debit - credit
        return credit - debit


class JournalEntry(models.Model):
    date = models.DateField(default=timezone.localdate)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"Entry #{self.pk} — {self.date}"

    @property
    def total_debits(self):
        return self.lines.aggregate(s=models.Sum("debit"))["s"] or Decimal("0.00")

    @property
    def total_credits(self):
        return self.lines.aggregate(s=models.Sum("credit"))["s"] or Decimal("0.00")

    @property
    def is_balanced(self):
        return self.total_debits == self.total_credits


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, related_name="lines", on_delete=models.CASCADE)
    account = models.ForeignKey(Account, related_name="lines", on_delete=models.PROTECT)
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.account.code}: D{self.debit} C{self.credit}"


@receiver(pre_delete, sender=JournalEntry)
def delete_sources_on_journal_delete(sender, instance, **kwargs):
    from sales.models import Sale
    from purchases.models import Purchase, PurchaseLine
    from inventory.models import JewelryItem

    purchase_ids = list(Purchase.objects.filter(journal_entry=instance).values_list("pk", flat=True))
    sale_ids = list(Sale.objects.filter(journal_entry=instance).values_list("pk", flat=True))
    item_ids = list(
        PurchaseLine.objects
        .filter(purchase_id__in=purchase_ids, created_item__isnull=False)
        .values_list("created_item_id", flat=True)
    )

    if item_ids:
        try:
            JewelryItem.objects.filter(pk__in=item_ids).delete()
        except ProtectedError:
            pass

    Purchase.objects.filter(pk__in=purchase_ids).update(journal_entry=None)
    Sale.objects.filter(pk__in=sale_ids).update(journal_entry=None)
    Purchase.objects.filter(pk__in=purchase_ids).delete()
    Sale.objects.filter(pk__in=sale_ids).delete()