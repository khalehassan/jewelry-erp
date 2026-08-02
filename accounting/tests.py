from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from purchases.models import Purchase, PurchaseLine
from sales.models import Sale, SaleLine
from .models import Account, JournalEntry, JournalLine
from .services import create_entry


class GoldMovementReportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="report-owner",
            password="test-password",
        )
        permission = Permission.objects.get(
            content_type__app_label="accounting",
            codename="view_account",
        )
        self.user.user_permissions.add(permission)
        self.client.force_login(self.user)

    def _at(self, year, month, day, hour):
        return timezone.make_aware(datetime(year, month, day, hour, 0))

    def test_purchase_and_sale_are_transaction_rows_with_running_balance(self):
        purchase = Purchase.objects.create()
        line_21k = PurchaseLine.objects.create(
            purchase=purchase,
            name="21K chain",
            karat=21,
            weight_grams=Decimal("2.000"),
            unit_cost=Decimal("2000.00"),
            quantity=2,
        )
        Purchase.objects.filter(pk=purchase.pk).update(
            created_at=self._at(2026, 7, 10, 9)
        )

        sale = Sale.objects.create()
        SaleLine.objects.create(
            sale=sale,
            item=line_21k.created_item,
            gold_price_per_gram=Decimal("3000.00"),
            quantity=1,
        )
        Sale.objects.filter(pk=sale.pk).update(
            created_at=self._at(2026, 7, 10, 11)
        )

        response = self.client.get(reverse("accounting:gold_movement"), {
            "from": "2026-07-10",
            "to": "2026-07-10",
        })

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        self.assertEqual(len(rows), 2)

        self.assertEqual(rows[0]["kind"], "Purchase")
        self.assertEqual(rows[0]["received"], "4.000")
        self.assertEqual(rows[0]["out"], "—")
        self.assertEqual(rows[0]["balance"], "4.000")

        self.assertEqual(rows[1]["kind"], "Sale")
        self.assertEqual(rows[1]["received"], "—")
        self.assertEqual(rows[1]["out"], "2.000")
        self.assertEqual(rows[1]["balance"], "2.000")

        summary_21k = response.context["summaries"][1]
        self.assertEqual(summary_21k["received"], "4.000")
        self.assertEqual(summary_21k["out"], "2.000")
        self.assertEqual(summary_21k["closing"], "2.000")

    def test_filtered_ledger_carries_forward_opening_balance(self):
        opening = Purchase.objects.create(is_opening=True)
        PurchaseLine.objects.create(
            purchase=opening,
            name="Opening 18K gold",
            karat=18,
            weight_grams=Decimal("3.000"),
            unit_cost=Decimal("1500.00"),
            quantity=1,
        )
        Purchase.objects.filter(pk=opening.pk).update(
            created_at=self._at(2026, 6, 30, 12)
        )

        purchase = Purchase.objects.create()
        PurchaseLine.objects.create(
            purchase=purchase,
            name="18K ring",
            karat=18,
            weight_grams=Decimal("2.000"),
            unit_cost=Decimal("1000.00"),
            quantity=2,
        )
        Purchase.objects.filter(pk=purchase.pk).update(
            created_at=self._at(2026, 7, 1, 9)
        )

        response = self.client.get(reverse("accounting:gold_movement"), {
            "from": "2026-07-01",
            "to": "2026-07-01",
        })

        rows = response.context["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "Purchase")
        self.assertEqual(rows[0]["received"], "4.000")
        self.assertEqual(rows[0]["balance"], "7.000")

        summary_18k = response.context["summaries"][0]
        self.assertEqual(summary_18k["opening"], "3.000")
        self.assertEqual(summary_18k["received"], "4.000")
        self.assertEqual(summary_18k["closing"], "7.000")

    def test_report_requires_accounting_view_permission(self):
        user_without_permission = get_user_model().objects.create_user(
            username="sales-clerk",
            password="test-password",
        )
        self.client.force_login(user_without_permission)

        response = self.client.get(reverse("accounting:gold_movement"))

        self.assertRedirects(response, reverse("sales:dashboard"))


class AutomatedPostingControlTests(TestCase):
    def setUp(self):
        self.cash = Account.objects.get(code="1011")
        self.capital = Account.objects.get(code="3010")

    def test_valid_automated_entry_is_rounded_and_balanced_at_egp_precision(self):
        entry = create_entry(timezone.localdate(), "Valid automated entry", [
            (self.cash.code, Decimal("100.005"), Decimal("0")),
            (self.capital.code, Decimal("0"), Decimal("100.005")),
        ])

        self.assertTrue(entry.is_balanced)
        self.assertEqual(entry.total_debits, Decimal("100.01"))
        self.assertEqual(entry.total_credits, Decimal("100.01"))
        self.assertEqual(entry.lines.count(), 2)

    def test_negative_automated_lines_are_rejected_before_any_write(self):
        invalid_entries = [
            [
                (self.cash.code, Decimal("-100.00"), Decimal("0")),
                (self.capital.code, Decimal("0"), Decimal("-100.00")),
            ],
            [
                (self.cash.code, Decimal("100.00"), Decimal("-1.00")),
                (self.capital.code, Decimal("0"), Decimal("101.00")),
            ],
        ]

        for lines in invalid_entries:
            with self.subTest(lines=lines):
                with self.assertRaisesMessage(ValidationError, "cannot be negative"):
                    create_entry(timezone.localdate(), "Invalid negative entry", lines)

        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(JournalLine.objects.count(), 0)

    def test_zero_both_sides_and_nonfinite_lines_are_rejected(self):
        invalid_entries = [
            (
                [
                    (self.cash.code, Decimal("0"), Decimal("0")),
                    (self.capital.code, Decimal("0"), Decimal("0")),
                ],
                "exactly one side",
            ),
            (
                [
                    (self.cash.code, Decimal("100"), Decimal("100")),
                    (self.capital.code, Decimal("100"), Decimal("100")),
                ],
                "exactly one side",
            ),
            (
                [
                    (self.cash.code, Decimal("NaN"), Decimal("0")),
                    (self.capital.code, Decimal("0"), Decimal("1")),
                ],
                "finite monetary amount",
            ),
            (
                [
                    (self.cash.code, Decimal("0.004"), Decimal("0")),
                    (self.capital.code, Decimal("0"), Decimal("0.004")),
                ],
                "rounds to zero",
            ),
        ]

        for lines, message in invalid_entries:
            with self.subTest(lines=lines):
                with self.assertRaisesMessage(ValidationError, message):
                    create_entry(timezone.localdate(), "Invalid line shape", lines)

        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_unbalanced_group_unknown_and_too_short_entries_are_rejected(self):
        group = Account.objects.filter(is_group=True).first()
        invalid_entries = [
            (
                [
                    (self.cash.code, Decimal("100"), Decimal("0")),
                    (self.capital.code, Decimal("0"), Decimal("99")),
                ],
                "not balanced",
            ),
            (
                [
                    (group.code, Decimal("100"), Decimal("0")),
                    (self.capital.code, Decimal("0"), Decimal("100")),
                ],
                "heading, not a postable account",
            ),
            (
                [
                    ("DOES-NOT-EXIST", Decimal("100"), Decimal("0")),
                    (self.capital.code, Decimal("0"), Decimal("100")),
                ],
                "unknown account code",
            ),
            (
                [(self.cash.code, Decimal("100"), Decimal("0"))],
                "at least two posting lines",
            ),
        ]

        for lines, message in invalid_entries:
            with self.subTest(lines=lines):
                with self.assertRaisesMessage(ValidationError, message):
                    create_entry(timezone.localdate(), "Invalid automated entry", lines)

        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_model_and_database_reject_invalid_individual_lines(self):
        entry = JournalEntry.objects.create(description="Constraint test")

        with self.assertRaises(ValidationError):
            JournalLine.objects.create(
                entry=entry,
                account=self.cash,
                debit=Decimal("-1.00"),
                credit=Decimal("0.00"),
            )

        group = Account.objects.filter(is_group=True).first()
        with self.assertRaisesMessage(ValidationError, "heading, not a postable account"):
            JournalLine.objects.create(
                entry=entry,
                account=group,
                debit=Decimal("1.00"),
                credit=Decimal("0.00"),
            )

        invalid_lines = [
            JournalLine(
                entry=entry,
                account=self.cash,
                debit=Decimal("-1.00"),
                credit=Decimal("0.00"),
            ),
            JournalLine(
                entry=entry,
                account=self.cash,
                debit=Decimal("1.00"),
                credit=Decimal("1.00"),
            ),
            JournalLine(
                entry=entry,
                account=self.cash,
                debit=Decimal("0.00"),
                credit=Decimal("0.00"),
            ),
        ]
        for line in invalid_lines:
            with self.subTest(debit=line.debit, credit=line.credit):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        JournalLine.objects.bulk_create([line])

        self.assertFalse(entry.is_balanced)
        self.assertEqual(entry.lines.count(), 0)
