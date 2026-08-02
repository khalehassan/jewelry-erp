from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from inventory.models import JewelryItem
from .models import Sale, SaleLine


class SaleValidationTests(TestCase):
    def setUp(self):
        self.item = JewelryItem.objects.create(
            name="21K test ring",
            category=JewelryItem.Category.RING,
            karat=JewelryItem.Karat.K21,
            weight_grams=Decimal("1.000"),
            location=JewelryItem.Location.SAFE,
            cost_price=Decimal("500.00"),
            quantity=3,
        )

    def _line_values(self, **overrides):
        values = {
            "item": self.item,
            "gold_price_per_gram": Decimal("1000.00"),
            "making_charge_per_gram": Decimal("0.00"),
            "quantity": 1,
        }
        values.update(overrides)
        return values

    def test_model_rejects_overselling_without_changing_stock(self):
        sale = Sale.objects.create()

        with self.assertRaisesMessage(ValidationError, "Not enough stock"):
            SaleLine.objects.create(sale=sale, **self._line_values(quantity=4))

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 3)
        self.assertFalse(sale.lines.exists())

    def test_repeated_item_is_rejected_without_second_stock_reduction(self):
        sale = Sale.objects.create()
        SaleLine.objects.create(sale=sale, **self._line_values(quantity=2))
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)

        with self.assertRaisesMessage(ValidationError, "same inventory item"):
            SaleLine.objects.create(sale=sale, **self._line_values(quantity=1))

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)
        self.assertEqual(sale.lines.count(), 1)

    def test_stock_reservation_tracks_unposted_line_changes_and_deletion(self):
        sale = Sale.objects.create()
        line = SaleLine.objects.create(sale=sale, **self._line_values(quantity=1))
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 2)

        line.quantity = 2
        line.save()
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)

        line.quantity = 1
        line.save()
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 2)

        line.delete()
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 3)

    def test_model_rejects_nonpositive_prices_negative_making_and_quantity(self):
        invalid_values = [
            {"gold_price_per_gram": Decimal("0.00")},
            {"gold_price_per_gram": Decimal("-1.00")},
            {"making_charge_per_gram": Decimal("-1.00")},
            {"quantity": 0},
            {"quantity": -1},
        ]

        for overrides in invalid_values:
            with self.subTest(values=overrides):
                sale = Sale.objects.create()
                with self.assertRaises(ValidationError):
                    SaleLine.objects.create(sale=sale, **self._line_values(**overrides))

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 3)
        self.assertEqual(SaleLine.objects.count(), 0)

    def test_database_constraints_reject_bypassed_invalid_values(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Sale.objects.bulk_create([Sale(discount=Decimal("-1.00"))])

        sale = Sale.objects.create()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SaleLine.objects.bulk_create([
                    SaleLine(
                        sale=sale,
                        **self._line_values(gold_price_per_gram=Decimal("0.00")),
                    )
                ])

    def test_empty_and_nonpositive_total_cannot_post_to_ledger(self):
        empty_sale = Sale.objects.create()
        with self.assertRaisesMessage(ValidationError, "at least one item"):
            empty_sale.post_to_ledger()

        sale = Sale.objects.create()
        SaleLine.objects.create(sale=sale, **self._line_values())
        Sale.objects.filter(pk=sale.pk).update(discount=Decimal("1000.00"))
        sale.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "greater than zero"):
            sale.post_to_ledger()


class SalePageValidationTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("sales-clerk", password="test")
        self.client.force_login(user)
        self.item = JewelryItem.objects.create(
            name="18K test bracelet",
            category=JewelryItem.Category.BRACELET,
            karat=JewelryItem.Karat.K18,
            weight_grams=Decimal("1.000"),
            location=JewelryItem.Location.SHOWCASE,
            cost_price=Decimal("400.00"),
            quantity=3,
        )

    def _post(self, **overrides):
        values = {
            "item": [str(self.item.pk)],
            "gold": ["1000.00"],
            "making": ["0.00"],
            "qty": ["1"],
            "discount": "0.00",
        }
        values.update(overrides)
        return self.client.post(reverse("sales:new_sale"), values, follow=True)

    def assert_nothing_was_sold(self):
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 3)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(SaleLine.objects.count(), 0)

    def test_repeated_rows_are_rejected_as_one_atomic_transaction(self):
        response = self._post(
            item=[str(self.item.pk), str(self.item.pk)],
            gold=["1000.00", "1000.00"],
            making=["0.00", "0.00"],
            qty=["2", "2"],
        )

        self.assertContains(response, "Each inventory item can appear only once")
        self.assert_nothing_was_sold()

    def test_negative_total_is_rejected_as_one_atomic_transaction(self):
        response = self._post(discount="1001.00")

        self.assertContains(response, "Sale total must be greater than zero")
        self.assert_nothing_was_sold()

    def test_valid_sale_reserves_stock_and_posts_one_ledger_entry(self):
        response = self._post(
            gold=["1000.00"],
            making=["100.00"],
            qty=["2"],
            discount="100.00",
        )

        self.assertEqual(response.status_code, 200)
        sale = Sale.objects.get()
        self.assertIsNotNone(sale.journal_entry_id)
        self.assertEqual(sale.lines.count(), 1)
        self.assertEqual(sale.total, Decimal("2100.00000"))
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)

    def test_zero_and_negative_values_are_rejected(self):
        invalid_posts = [
            ({"gold": ["0.00"]}, "Gold price per gram must be greater than zero"),
            ({"gold": ["-1.00"]}, "Gold price per gram must be greater than zero"),
            ({"making": ["-1.00"]}, "Making charge cannot be negative"),
            ({"qty": ["0"]}, "Quantity must be at least 1"),
            ({"qty": ["-1"]}, "Quantity must be at least 1"),
            ({"discount": "-1.00"}, "Discount cannot be negative"),
        ]

        for overrides, message in invalid_posts:
            with self.subTest(values=overrides):
                response = self._post(**overrides)
                self.assertContains(response, message)
                self.assert_nothing_was_sold()
