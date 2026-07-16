from .models import Account, JournalEntry, JournalLine


def create_entry(date, description, lines):
    """lines: a list of (account_code, debit, credit) tuples."""
    entry = JournalEntry.objects.create(date=date, description=description)
    for code, debit, credit in lines:
        JournalLine.objects.create(
            entry=entry,
            account=Account.objects.get(code=code),
            debit=debit,
            credit=credit,
        )
    return entry
