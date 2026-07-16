from decimal import Decimal

from django.db import models
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
        # Assets & expenses are debit-normal; liabilities, equity & revenue are credit-normal
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