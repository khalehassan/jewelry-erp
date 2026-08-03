from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Account, JournalEntry, JournalLine

# Once a transaction is posted to the ledger it is locked. Corrections are new
# audit-trail transactions rather than destructive edits to posted history.
POSTED_LOCK_MESSAGE = (
    "{what} is already posted to the ledger and cannot be changed. "
    "Record a correcting transaction if it is wrong."
)


def deletion_origin_includes(origin, model, pk):
    """True when ``model(pk)`` is the root of the current delete operation."""
    if isinstance(origin, model):
        return origin.pk == pk
    if getattr(origin, "model", None) is model:
        return origin.filter(pk=pk).exists()
    return False


def create_entry(
    date,
    description,
    lines,
    *,
    source=JournalEntry.Source.AUTOMATED,
    created_by=None,
):
    """lines: a list of (account_code, debit, credit) tuples."""
    try:
        raw_lines = list(lines)
    except TypeError as error:
        raise ValidationError("Journal lines must be an iterable of posting rows.") from error
    if len(raw_lines) < 2:
        raise ValidationError("A journal entry must contain at least two posting lines.")

    entry_candidate = JournalEntry(
        date=date,
        description=description,
        source=source,
        created_by=created_by,
    )
    entry_candidate.full_clean()

    # Resolve and validate every account and amount BEFORE creating anything,
    # so an automated caller can never leave a partial or invalid journal entry.
    resolved = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    cent = Decimal("0.01")
    for row_number, raw_line in enumerate(raw_lines, start=1):
        try:
            code, raw_debit, raw_credit = raw_line
        except (TypeError, ValueError) as error:
            raise ValidationError(
                f"Journal line {row_number} must contain account code, debit, and credit."
            ) from error

        try:
            account = Account.objects.get(code=str(code).strip())
        except Account.DoesNotExist as error:
            raise ValidationError(
                f"Journal line {row_number} uses unknown account code {code}."
            ) from error
        if account.is_group:
            raise ValidationError(
                f"{account} is a heading, not a postable account. "
                f"Post to one of its detail accounts instead."
            )

        amounts = []
        for side, raw_amount in (("debit", raw_debit), ("credit", raw_credit)):
            if isinstance(raw_amount, bool):
                raise ValidationError(
                    f"Journal line {row_number} {side} must be a valid monetary amount."
                )
            try:
                amount = Decimal(str(raw_amount))
            except (InvalidOperation, TypeError, ValueError) as error:
                raise ValidationError(
                    f"Journal line {row_number} {side} must be a valid monetary amount."
                ) from error
            if not amount.is_finite():
                raise ValidationError(
                    f"Journal line {row_number} {side} must be a finite monetary amount."
                )
            if amount < 0:
                raise ValidationError(
                    f"Journal line {row_number} {side} cannot be negative."
                )
            amounts.append(amount)

        raw_debit, raw_credit = amounts
        if (raw_debit > 0) == (raw_credit > 0):
            raise ValidationError(
                f"Journal line {row_number} must have a positive amount on exactly one side."
            )

        try:
            debit = raw_debit.quantize(cent, rounding=ROUND_HALF_UP)
            credit = raw_credit.quantize(cent, rounding=ROUND_HALF_UP)
        except InvalidOperation as error:
            raise ValidationError(
                f"Journal line {row_number} contains an amount outside the supported range."
            ) from error
        if debit == 0 and credit == 0:
            raise ValidationError(
                f"Journal line {row_number} amount rounds to zero at EGP precision."
            )

        candidate = JournalLine(account=account, debit=debit, credit=credit)
        candidate.full_clean(exclude=("entry",))
        resolved.append((account, debit, credit))
        total_debit += debit
        total_credit += credit

    if total_debit <= 0 or total_debit != total_credit:
        raise ValidationError(
            f"Journal entry is not balanced: debits ({total_debit:,.2f}) "
            f"must equal credits ({total_credit:,.2f}) and be greater than zero."
        )

    with transaction.atomic():
        entry_candidate.save()
        for account, debit, credit in resolved:
            JournalLine.objects.create(
                entry=entry_candidate,
                account=account,
                debit=debit,
                credit=credit,
            )
        if not entry_candidate.is_balanced:
            raise ValidationError("Journal entry failed its final balance verification.")
    return entry_candidate
