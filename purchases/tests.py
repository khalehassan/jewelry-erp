from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import RestrictedError
from django.test import TestCase, TransactionTestCase

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


class PurchaseInventoryDeletionTests(TransactionTestCase):
    def _purchase_with_item(self, weight="2.000", quantity=2):
        purchase = Purchase.objects.create()
        line = PurchaseLine.objects.create(
            purchase=purchase,
            name="21K test chain",
            karat=21,
            weight_grams=Decimal(weight),
            unit_cost=Decimal("1000.00"),
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
