from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
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
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children",
        help_text="The heading this account sits under, e.g. 1011 Cash on Hand sits under 1010",
    )
    is_group = models.BooleanField(
        default=False,
        help_text="A heading that totals its children. You cannot post transactions to a group account.",
    )

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.name}"

    @property
    def depth(self):
        """How many headings sit above this account — used to indent the report."""
        level = 0
        node = self.parent
        while node is not None and level < 10:
            level += 1
            node = node.parent
        return level

    @property
    def descendant_ids(self):
        """This account's own id plus every account nested underneath it."""
        ids = [self.pk]
        for child in self.children.all():
            ids.extend(child.descendant_ids)
        return ids

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
        return self.total_debits > 0 and self.total_debits == self.total_credits


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, related_name="lines", on_delete=models.CASCADE)
    account = models.ForeignKey(Account, related_name="lines", on_delete=models.PROTECT)
    debit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    credit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(debit__gte=0),
                name="journal_line_debit_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(credit__gte=0),
                name="journal_line_credit_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(debit__gt=0, credit=0)
                    | models.Q(debit=0, credit__gt=0)
                ),
                name="journal_line_exactly_one_side",
            ),
        ]

    def __str__(self):
        return f"{self.account.code}: D{self.debit} C{self.credit}"

    def clean(self):
        super().clean()
        if self.account_id:
            account = Account.objects.filter(pk=self.account_id).first()
            if account is not None and account.is_group:
                raise ValidationError({
                    "account": (
                        f"{account} is a heading, not a postable account. "
                        "Choose a detail account beneath it."
                    ),
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
