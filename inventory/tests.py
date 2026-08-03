from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounting.models import JournalEntry
from purchases.models import Purchase, PurchaseLine
from .models import JewelryItem


class StockImportValidationTests(TestCase):
    headers = (
        "barcode,name,category,karat,weight_grams,raw_gold_price_per_gram,"
        "craftsmanship_per_gram,stamp_charge,location,quantity"
    )

    def setUp(self):
        user = get_user_model().objects.create_user("stock-importer", password="test")
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label="inventory",
            codename="add_jewelryitem",
        ))
        self.client.force_login(user)

    def _upload(self, rows, headers=None, raw_bytes=None):
        if raw_bytes is None:
            csv_text = "\n".join([headers or self.headers, *rows])
            raw_bytes = csv_text.encode("utf-8")
        upload = SimpleUploadedFile("stock.csv", raw_bytes, content_type="text/csv")
        return self.client.post(
            reverse("inventory:import_stock"),
            {"file": upload},
            follow=True,
        )

    def assert_no_import_records(self):
        self.assertEqual(Purchase.objects.filter(is_opening=True).count(), 0)
        self.assertEqual(PurchaseLine.objects.count(), 0)
        self.assertEqual(JewelryItem.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_valid_rows_create_one_complete_opening_stock_batch(self):
        response = self._upload([
            "TAG-001,Gold Ring,Ring,21,4.500,2500.00,100.00,50.00,SAFE,1",
            ",Gold Chain,chain,18,8.250,2600.00,150.00,75.00,showcase,2",
        ])

        self.assertContains(response, "Imported 2 item(s) as Opening stock")
        batch = Purchase.objects.get(is_opening=True)
        self.assertIsNotNone(batch.journal_entry_id)
        self.assertEqual(batch.lines.count(), 2)
        self.assertEqual(JewelryItem.objects.count(), 2)
        ring = JewelryItem.objects.get(barcode="TAG-001")
        self.assertEqual(ring.category, JewelryItem.Category.RING)
        self.assertEqual(ring.location, JewelryItem.Location.SAFE)
        self.assertEqual(ring.weight_grams, Decimal("4.500"))
        self.assertEqual(ring.cost_price, Decimal("11750.00"))

    def test_each_invalid_controlled_field_cancels_the_import(self):
        invalid_rows = [
            ("TAG-001,Gold Ring,watch,21,4.500,2500.00,100.00,50.00,safe,1", "category must be one of"),
            ("TAG-001,Gold Ring,ring,22,4.500,2500.00,100.00,50.00,safe,1", "karat must be one of"),
            ("TAG-001,Gold Ring,ring,21,4.500,2500.00,100.00,50.00,vault,1", "location must be one of"),
            ("TAG-001,Gold Ring,ring,21,0,2500.00,100.00,50.00,safe,1", "weight_grams must be greater than zero"),
            ("TAG-001,Gold Ring,ring,21,-1,2500.00,100.00,50.00,safe,1", "weight_grams must be greater than zero"),
            ("TAG-001,Gold Ring,ring,21,abc,2500.00,100.00,50.00,safe,1", "weight_grams must be a valid number"),
            ("TAG-001,Gold Ring,ring,21,4.500,0,100.00,50.00,safe,1", "raw_gold_price_per_gram must be greater than zero"),
            ("TAG-001,Gold Ring,ring,21,4.500,-1,100.00,50.00,safe,1", "raw_gold_price_per_gram must be greater than zero"),
            ("TAG-001,Gold Ring,ring,21,4.500,abc,100.00,50.00,safe,1", "raw_gold_price_per_gram must be a valid number"),
            ("TAG-001,Gold Ring,ring,21,4.500,2500.00,-1,50.00,safe,1", "craftsmanship_per_gram cannot be negative"),
            ("TAG-001,Gold Ring,ring,21,4.500,2500.00,abc,50.00,safe,1", "craftsmanship_per_gram must be a valid number"),
            ("TAG-001,Gold Ring,ring,21,4.500,2500.00,100.00,-1,safe,1", "stamp_charge cannot be negative"),
            ("TAG-001,Gold Ring,ring,21,4.500,2500.00,100.00,abc,safe,1", "stamp_charge must be a valid number"),
            ("TAG-001,Gold Ring,ring,21,4.500,2500.00,100.00,50.00,safe,0", "quantity must be at least 1"),
            ("TAG-001,Gold Ring,ring,21,4.500,2500.00,100.00,50.00,safe,-1", "quantity must be at least 1"),
            ("TAG-001,Gold Ring,ring,21,4.500,2500.00,100.00,50.00,safe,1.5", "quantity must be a whole number"),
        ]

        for row, message in invalid_rows:
            with self.subTest(row=row):
                response = self._upload([row])
                self.assertContains(response, "Import cancelled")
                self.assertContains(response, message)
                self.assert_no_import_records()

    def test_one_invalid_row_rolls_back_other_valid_rows(self):
        response = self._upload([
            "TAG-001,Valid Ring,ring,21,4.500,2500.00,100.00,50.00,safe,1",
            "TAG-002,Invalid Ring,ring,99,3.000,2500.00,100.00,50.00,safe,1",
        ])

        self.assertContains(response, "Row 3")
        self.assertContains(response, "Import cancelled")
        self.assert_no_import_records()

    def test_missing_headers_and_invalid_encoding_are_rejected(self):
        response = self._upload(
            ["TAG-001,Gold Ring,ring,21,4.500,100.00,50.00,safe,1"],
            headers=(
                "barcode,name,category,karat,weight_grams,"
                "craftsmanship_per_gram,stamp_charge,location,quantity"
            ),
        )
        self.assertContains(response, "Missing required column(s): raw_gold_price_per_gram")
        self.assert_no_import_records()

        response = self._upload([], raw_bytes=b"\xff\xfe\x00\x00")
        self.assertContains(response, "not a valid UTF-8 CSV")
        self.assert_no_import_records()

    def test_duplicate_barcodes_are_rejected_without_silent_replacement(self):
        response = self._upload([
            "TAG-001,Gold Ring,ring,21,4.500,2500.00,100.00,50.00,safe,1",
            "TAG-001,Gold Chain,chain,18,6.000,2500.00,100.00,50.00,safe,1",
        ])
        self.assertContains(response, "barcode TAG-001 is already used on row 2")
        self.assert_no_import_records()

        JewelryItem.objects.create(
            name="Existing item",
            barcode="EXISTING-001",
            category=JewelryItem.Category.RING,
            karat=JewelryItem.Karat.K21,
            weight_grams=Decimal("2.000"),
            cost_price=Decimal("5000.00"),
            location=JewelryItem.Location.SAFE,
            quantity=1,
        )
        response = self._upload([
            "EXISTING-001,Another Ring,ring,21,3.000,2500.00,100.00,50.00,safe,1",
        ])
        self.assertContains(response, "barcode EXISTING-001 already exists in inventory")
        self.assertEqual(Purchase.objects.filter(is_opening=True).count(), 0)
        self.assertEqual(PurchaseLine.objects.count(), 0)
        self.assertEqual(JewelryItem.objects.count(), 1)
