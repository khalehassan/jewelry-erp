from django.db import transaction

from .models import Account, JournalEntry, JournalLine

# Once a transaction is posted to the ledger it is locked: correcting it means
# deleting it (which removes its journal entry) and entering it again.
POSTED_LOCK_MESSAGE = (
    "{what} is already posted to the ledger and cannot be changed. "
    "Delete it and enter it again if it is wrong — deleting also removes its journal entry."
)


def create_entry(date, description, lines):
    """lines: a list of (account_code, debit, credit) tuples."""
    # Resolve and check every account BEFORE creating anything, so a bad line
    # can't leave a half-written entry behind.
    resolved = []
    for code, debit, credit in lines:
        account = Account.objects.get(code=code)
        if account.is_group:
            raise ValueError(
                f"{account} is a heading, not a postable account. "
                f"Post to one of its detail accounts instead."
            )
        resolved.append((account, debit, credit))

    with transaction.atomic():
        entry = JournalEntry.objects.create(date=date, description=description)
        for account, debit, credit in resolved:
            JournalLine.objects.create(entry=entry, account=account, debit=debit, credit=credit)
    return entry
