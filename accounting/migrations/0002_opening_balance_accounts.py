from django.db import migrations


NEW_ACCOUNTS = [
    ("1010", "Bank", "asset"),
    ("3100", "Opening Balance Equity", "equity"),
    ("3200", "Retained Earnings", "equity"),
]


def add_accounts(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    for code, name, type_ in NEW_ACCOUNTS:
        Account.objects.get_or_create(code=code, defaults={"name": name, "type": type_})
    # Align 3000 with standard terminology (same account, same balance — name only)
    Account.objects.filter(code="3000").update(name="Owner's Capital")


def remove_accounts(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    for code, _name, _type in NEW_ACCOUNTS:
        acct = Account.objects.filter(code=code).first()
        if acct and not acct.lines.exists():
            acct.delete()
    Account.objects.filter(code="3000").update(name="Owner's Equity")


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_accounts, remove_accounts),
    ]
