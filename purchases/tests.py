from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import RestrictedError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounting.models import JournalEntry
from inventory.models import JewelryItem
from sales.models import Sale, SaleLine

from .models import Purchase, PurchaseLine, Supplier


class SupplierDuplicateTests(TestCase):
    def test_supplier_identity_is_normalized(self):
        supplier = Supplier.objects.create(
            name="  Cairo   Gold  ",
            phone="(010) 9350-7625",
            email=" SALES@CAIROGOLD.COM ",
        )

        self.assertEqual(supplier.name, "Cairo Gold")
        self.assertEqual(supplier.phone, "01093507625")
        self.assertEqual(supplier.email, "sales@cairogold.com")

    def test_duplicate_supplier_name_phone_or_email_is_rejected(self):
        Supplier.objects.create(
            name="Cairo Gold",
            phone="01093507625",
            email="sales@cairogold.com",
        )

        duplicates = [
            Supplier(name=" CAIRO   GOLD "),
            Supplier(name="Different Supplier", phone="0109 350-7625"),
            Supplier(name="Another Supplier", email="SALES@CAIROGOLD.COM"),
        ]
        for duplicate in duplicates:
            with self.subTest(supplier=duplicate.name):
                with self.assertRaises(ValidationError):
                    duplicate.save()


class PurchaseAmountValidationTests(TestCase):
    def test_model_rejects_zero_and_negative_purchase_values(self):
        invalid_values = [
            {"weight_grams": Decimal("0.000")},
            {"weight_grams": Decimal("-1.000")},
            {"raw_gold_price_per_gram": Decimal("0.00")},
            {"raw_gold_price_per_gram": Decimal("-200.00")},
            {"craftsmanship_per_gram": Decimal("-1.00")},
            {"stamp_charge": Decimal("-1.00")},
            {"quantity": 0},
            {"quantity": -1},
        ]

        for overrides in invalid_values:
            with self.subTest(values=overrides):
                purchase = Purchase.objects.create()
                values = {
                    "purchase": purchase,
                    "name": "Invalid item",
                    "karat": 21,
                    "weight_grams": Decimal("2.000"),
                    "raw_gold_price_per_gram": Decimal("500.00"),
                    "craftsmanship_per_gram": Decimal("0.00"),
                    "stamp_charge": Decimal("0.00"),
                    "quantity": 1,
                }
                values.update(overrides)
                with self.assertRaises(ValidationError):
                    PurchaseLine.objects.create(**values)

    def test_database_constraints_reject_bypassed_invalid_cost_components(self):
        purchase = Purchase.objects.create()
        invalid_values = [
            {"raw_gold_price_per_gram": Decimal("0.00")},
            {"craftsmanship_per_gram": Decimal("-1.00")},
            {"stamp_charge": Decimal("-1.00")},
        ]

        for overrides in invalid_values:
            with self.subTest(values=overrides):
                values = {
                    "purchase": purchase,
                    "name": "Bypassed invalid item",
                    "karat": 21,
                    "weight_grams": Decimal("2.000"),
                    "raw_gold_price_per_gram": Decimal("500.00"),
                    "craftsmanship_per_gram": Decimal("0.00"),
                    "stamp_charge": Decimal("0.00"),
                    "quantity": 1,
                }
                values.update(overrides)
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        PurchaseLine.objects.bulk_create([PurchaseLine(**values)])

    def test_cost_components_calculate_piece_stock_and_row_totals(self):
        purchase = Purchase.objects.create()
        line = PurchaseLine.objects.create(
            purchase=purchase,
            name="Costed gold ring",
            karat=21,
            weight_grams=Decimal("4.000"),
            raw_gold_price_per_gram=Decimal("3000.00"),
            craftsmanship_per_gram=Decimal("200.00"),
            stamp_charge=Decimal("50.00"),
            quantity=2,
        )

        self.assertEqual(line.cost_per_piece, Decimal("12850.00"))
        self.assertEqual(line.line_total, Decimal("25700.00"))
        self.assertEqual(purchase.total, Decimal("25700.00"))
        self.assertEqual(line.created_item.cost_price, Decimal("12850.00"))

        purchase.post_to_ledger()
        self.assertEqual(purchase.journal_entry.total_debits, Decimal("25700.00"))
        self.assertEqual(purchase.journal_entry.total_credits, Decimal("25700.00"))

    def test_empty_purchase_cannot_be_posted(self):
        purchase = Purchase.objects.create()

        with self.assertRaisesMessage(
            ValidationError,
            "A purchase must contain at least one item.",
        ):
            purchase.post_to_ledger()

    def test_purchase_page_rejects_empty_and_negative_purchases(self):
        user = get_user_model().objects.create_user("purchase-clerk", password="test")
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label="purchases",
            codename="add_purchase",
        ))
        self.client.force_login(user)

        empty_response = self.client.post(
            reverse("purchases:new_purchase"),
            {},
            follow=True,
        )
        self.assertContains(empty_response, "A purchase must contain at least one item.")

        negative_response = self.client.post(reverse("purchases:new_purchase"), {
            "barcode": [""],
            "name": ["Negative item"],
            "category": ["ring"],
            "karat": ["21"],
            "weight": ["2.000"],
            "stone": [""],
            "location": ["safe"],
            "raw_gold_price": ["-200.00"],
            "craftsmanship": ["0.00"],
            "stamp": ["0.00"],
            "qty": ["1"],
        }, follow=True)
        self.assertContains(negative_response, "Raw gold price per gram must be greater than zero.")
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertEqual(PurchaseLine.objects.count(), 0)
        self.assertEqual(JewelryItem.objects.count(), 0)

    def test_purchase_page_saves_the_new_cost_components(self):
        user = get_user_model().objects.create_user("purchase-user", password="test")
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label="purchases",
            codename="add_purchase",
        ))
        self.client.force_login(user)

        page = self.client.get(reverse("purchases:new_purchase"))
        self.assertContains(page, 'name="raw_gold_price"')
        self.assertContains(page, 'name="craftsmanship"')
        self.assertContains(page, 'name="stamp"')
        self.assertNotContains(page, 'name="cost"')

        response = self.client.post(reverse("purchases:new_purchase"), {
            "barcode": ["COST-001"],
            "name": ["Costed ring"],
            "category": ["ring"],
            "karat": ["21"],
            "weight": ["4.000"],
            "stone": [""],
            "location": ["safe"],
            "raw_gold_price": ["3000.00"],
            "craftsmanship": ["200.00"],
            "stamp": ["50.00"],
            "qty": ["2"],
        }, follow=True)

        self.assertContains(response, "total 25,700.00 EGP")
        line = PurchaseLine.objects.get()
        self.assertEqual(line.raw_gold_price_per_gram, Decimal("3000.000000000"))
        self.assertEqual(line.craftsmanship_per_gram, Decimal("200.00"))
        self.assertEqual(line.stamp_charge, Decimal("50.00"))
        self.assertEqual(line.cost_per_piece, Decimal("12850.00"))
        self.assertEqual(line.line_total, Decimal("25700.00"))
        self.assertEqual(line.created_item.cost_price, Decimal("12850.00"))
        self.assertIsNotNone(line.purchase.journal_entry_id)


class PurchaseInventoryDeletionTests(TransactionTestCase):
    def _purchase_with_item(self, weight="2.000", quantity=2):
        purchase = Purchase.objects.create()
        line = PurchaseLine.objects.create(
            purchase=purchase,
            name="21K test chain",
            karat=21,
            weight_grams=Decimal(weight),
            raw_gold_price_per_gram=Decimal("500.00"),
            craftsmanship_per_gram=Decimal("0.00"),
            stamp_charge=Decimal("0.00"),
            quantity=quantity,
        )
        return purchase, line, line.created_item

    def _sale_one(self, item):
        sale = Sale.objects.create()
        SaleLine.objects.create(
            sale=sale,
            item=item,
            gold_price_per_gram=Decimal("3000.00"),
            quantity=1,
        )
        return sale

    def test_purchase_deletion_is_blocked_while_item_is_used_by_sale(self):
        purchase, line, item = self._purchase_with_item()
        sale = self._sale_one(item)

        with self.assertRaises(RestrictedError):
            with transaction.atomic():
                purchase.delete()

        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists())
        self.assertTrue(PurchaseLine.objects.filter(pk=line.pk).exists())
        self.assertTrue(JewelryItem.objects.filter(pk=item.pk).exists())
        self.assertTrue(Sale.objects.filter(pk=sale.pk).exists())

    def test_inventory_item_cannot_be_deleted_away_from_its_purchase(self):
        purchase, line, item = self._purchase_with_item()

        with self.assertRaises(RestrictedError):
            with transaction.atomic():
                item.delete()

        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists())
        self.assertTrue(PurchaseLine.objects.filter(pk=line.pk).exists())
        self.assertTrue(JewelryItem.objects.filter(pk=item.pk).exists())

    def test_sale_then_purchase_deletion_removes_every_connected_record(self):
        purchase, line, item = self._purchase_with_item()
        sale = self._sale_one(item)

        sale.delete()
        purchase.delete()

        self.assertFalse(Sale.objects.filter(pk=sale.pk).exists())
        self.assertFalse(Purchase.objects.filter(pk=purchase.pk).exists())
        self.assertFalse(PurchaseLine.objects.filter(pk=line.pk).exists())
        self.assertFalse(JewelryItem.objects.filter(pk=item.pk).exists())

    def test_journal_deletion_cannot_orphan_item_used_by_sale(self):
        purchase, line, item = self._purchase_with_item()
        purchase_entry = JournalEntry.objects.create(description="Purchase test")
        Purchase.objects.filter(pk=purchase.pk).update(journal_entry=purchase_entry)
        sale = self._sale_one(item)

        with self.assertRaises(RestrictedError):
            with transaction.atomic():
                purchase_entry.delete()

        purchase.refresh_from_db()
        self.assertEqual(purchase.journal_entry_id, purchase_entry.pk)
        self.assertTrue(PurchaseLine.objects.filter(pk=line.pk).exists())
        self.assertTrue(JewelryItem.objects.filter(pk=item.pk).exists())
        self.assertTrue(Sale.objects.filter(pk=sale.pk).exists())

        sale.delete()
        purchase_entry.delete()

        self.assertFalse(JournalEntry.objects.filter(pk=purchase_entry.pk).exists())
        self.assertFalse(Purchase.objects.filter(pk=purchase.pk).exists())
        self.assertFalse(PurchaseLine.objects.filter(pk=line.pk).exists())
        self.assertFalse(JewelryItem.objects.filter(pk=item.pk).exists())

    def test_deleting_connected_sale_and_purchase_journals_removes_full_chain(self):
        purchase, line, item = self._purchase_with_item()
        purchase_entry = JournalEntry.objects.create(description="Purchase test")
        Purchase.objects.filter(pk=purchase.pk).update(journal_entry=purchase_entry)

        sale = self._sale_one(item)
        sale_entry = JournalEntry.objects.create(description="Sale test")
        Sale.objects.filter(pk=sale.pk).update(journal_entry=sale_entry)

        JournalEntry.objects.filter(pk__in=[purchase_entry.pk, sale_entry.pk]).delete()

        self.assertFalse(JournalEntry.objects.filter(
            pk__in=[purchase_entry.pk, sale_entry.pk]
        ).exists())
        self.assertFalse(Sale.objects.filter(pk=sale.pk).exists())
        self.assertFalse(Purchase.objects.filter(pk=purchase.pk).exists())
        self.assertFalse(PurchaseLine.objects.filter(pk=line.pk).exists())
        self.assertFalse(JewelryItem.objects.filter(pk=item.pk).exists())
