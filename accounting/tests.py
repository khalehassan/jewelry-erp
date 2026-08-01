from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from purchases.models import Purchase, PurchaseLine
from sales.models import Sale, SaleLine


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

    def _at_noon(self, year, month, day):
        return timezone.make_aware(datetime(year, month, day, 12, 0))

    def test_report_groups_daily_weights_and_excludes_opening_stock(self):
        purchase = Purchase.objects.create()
        PurchaseLine.objects.create(
            purchase=purchase,
            name="18K ring",
            karat=18,
            weight_grams=Decimal("4.000"),
            unit_cost=Decimal("1000.00"),
            quantity=1,
        )
        line_21k = PurchaseLine.objects.create(
            purchase=purchase,
            name="21K chain",
            karat=21,
            weight_grams=Decimal("10.000"),
            unit_cost=Decimal("2000.00"),
            quantity=2,
        )
        Purchase.objects.filter(pk=purchase.pk).update(
            created_at=self._at_noon(2026, 7, 10)
        )

        opening = Purchase.objects.create(is_opening=True)
        PurchaseLine.objects.create(
            purchase=opening,
            name="Opening 24K stock",
            karat=24,
            weight_grams=Decimal("100.000"),
            unit_cost=Decimal("5000.00"),
            quantity=1,
        )
        Purchase.objects.filter(pk=opening.pk).update(
            created_at=self._at_noon(2026, 7, 10)
        )

        sale = Sale.objects.create()
        SaleLine.objects.create(
            sale=sale,
            item=line_21k.created_item,
            gold_price_per_gram=Decimal("3000.00"),
            quantity=1,
        )
        Sale.objects.filter(pk=sale.pk).update(
            created_at=self._at_noon(2026, 7, 11)
        )

        response = self.client.get(reverse("accounting:gold_movement"), {
            "from": "2026-07-10",
            "to": "2026-07-12",
        })

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        self.assertEqual(len(rows), 3)

        self.assertEqual(rows[0]["movements"][0]["received"], "4.000")
        self.assertEqual(rows[0]["movements"][1]["received"], "20.000")
        self.assertEqual(rows[0]["movements"][2]["received"], "0.000")
        self.assertEqual(rows[0]["fine_received"], "20.500")

        self.assertEqual(rows[1]["movements"][1]["out"], "10.000")
        self.assertEqual(rows[1]["movements"][1]["net"], "-10.000")
        self.assertEqual(rows[1]["fine_out"], "8.750")
        self.assertEqual(rows[1]["fine_net"], "-8.750")

        self.assertEqual(rows[2]["fine_received"], "0.000")
        self.assertEqual(rows[2]["fine_out"], "0.000")
        self.assertEqual(response.context["total_fine_received"], "20.500")
        self.assertEqual(response.context["total_fine_out"], "8.750")
        self.assertEqual(response.context["total_fine_net"], "11.750")

        # The opening-stock line must not appear as 24K received movement.
        self.assertEqual(response.context["totals"][2]["received"], "0.000")

    def test_date_filter_excludes_movements_outside_the_period(self):
        purchase = Purchase.objects.create()
        PurchaseLine.objects.create(
            purchase=purchase,
            name="21K bracelet",
            karat=21,
            weight_grams=Decimal("7.500"),
            unit_cost=Decimal("1500.00"),
            quantity=1,
        )
        Purchase.objects.filter(pk=purchase.pk).update(
            created_at=self._at_noon(2026, 6, 30)
        )

        response = self.client.get(reverse("accounting:gold_movement"), {
            "from": "2026-07-01",
            "to": "2026-07-01",
        })

        self.assertEqual(response.context["total_fine_received"], "0.000")
        self.assertEqual(response.context["rows"][0]["movements"][1]["received"], "0.000")

    def test_report_requires_accounting_view_permission(self):
        user_without_permission = get_user_model().objects.create_user(
            username="sales-clerk",
            password="test-password",
        )
        self.client.force_login(user_without_permission)

        response = self.client.get(reverse("accounting:gold_movement"))

        self.assertRedirects(response, reverse("sales:dashboard"))
