from django.db import migrations


def create_other_payment_account(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    parent = Account.objects.get(code="1020")
    Account.objects.update_or_create(
        code="1025",
        defaults={
            "name": "Other Payment Account",
            "type": "asset",
            "parent": parent,
            "is_group": False,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0005_alter_journalline_credit_alter_journalline_debit_and_more"),
    ]

    operations = [
        migrations.RunPython(
            create_other_payment_account,
            migrations.RunPython.noop,
        ),
    ]
