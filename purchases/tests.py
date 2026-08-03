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
from payments.models import Payment
from sales.models import Sale, SaleLine

from .models import Purchase, PurchaseLine, Supplier


class PurchaseReversalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="reversal-controller",
            password="test-password",
            email="reversal@example.com",
        )

    def _posted_purchase(self, *, supplier=None, on_credit=False, quantity=2):
        purchase = Purchase.objects.create(
            supplier=supplier,
            on_credit=on_credit,
        )
        line = PurchaseLine.objects.create(
            purchase=purchase,
            name="Reversible 21K chain",
            category=JewelryItem.Category.CHAIN,
            karat=JewelryItem.Karat.K21,
            weight_grams=Decimal("2.000"),
            raw_gold_price_per_gram=Decimal("500.00"),
            craftsmanship_per_gram=Decimal("50.00"),
            stamp_charge=Decimal("25.00"),
            quantity=quantity,
        )
        purchase.post_to_ledger()
        purchase.refresh_from_db()
        return purchase, line, line.created_item

    def test_reversal_keeps_audit_record_and_undoes_inventory_and_ledger(self):
        purchase, line, item = self._posted_purchase()
        original_entry = purchase.journal_entry
        original_lines = {
            journal_line.account.code: (journal_line.debit, journal_line.credit)
            for journal_line in original_entry.lines.select_related("account")
        }
        item_id = item.pk

        reversal_entry = purchase.reverse(
            user=self.user,
            reason="Supplier invoice was entered twice",
        )

        purchase.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.Status.REVERSED)
        self.assertEqual(purchase.reversal_journal_entry_id, reversal_entry.pk)
        self.assertEqual(purchase.reversal_reason, "Supplier invoice was entered twice")
        self.assertEqual(purchase.reversed_by, self.user)
        self.assertIsNotNone(purchase.reversed_at)
        self.assertIsNone(line.created_item_id)
        self.assertFalse(JewelryItem.objects.filter(pk=item_id).exists())
        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists())
        self.assertTrue(PurchaseLine.objects.filter(pk=line.pk).exists())
        self.assertTrue(JournalEntry.objects.filter(pk=original_entry.pk).exists())

        reversed_lines = {
            journal_line.account.code: (journal_line.debit, journal_line.credit)
            for journal_line in reversal_entry.lines.select_related("account")
        }
        self.assertEqual(set(reversed_lines), set(original_lines))
        for code, (original_debit, original_credit) in original_lines.items():
            self.assertEqual(reversed_lines[code], (original_credit, original_debit))
        self.assertEqual(reversal_entry.total_debits, original_entry.total_credits)
        self.assertEqual(reversal_entry.total_credits, original_entry.total_debits)

        with self.assertRaisesMessage(ValidationError, "already been reversed"):
            purchase.reverse(user=self.user, reason="Try twice")
        with self.assertRaisesMessage(ValidationError, "permanent audit record"):
            purchase.delete()

    def test_reversal_is_blocked_when_item_has_been_used_on_a_sale(self):
        purchase, line, item = self._posted_purchase()
        sale = Sale.objects.create()
        SaleLine.objects.create(
            sale=sale,
            item=item,
            gold_price_per_gram=Decimal("1000.00"),
            making_charge_per_gram=Decimal("0.00"),
            quantity=1,
        )

        with self.assertRaisesMessage(ValidationError, "active sale"):
            purchase.reverse(user=self.user, reason="Incorrect supplier")

        purchase.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.Status.POSTED)
        self.assertIsNone(purchase.reversal_journal_entry_id)
        self.assertEqual(line.created_item_id, item.pk)
        self.assertTrue(JewelryItem.objects.filter(pk=item.pk).exists())

    def test_reversal_is_allowed_after_linked_sale_is_reversed(self):
        purchase, line, item = self._posted_purchase(quantity=2)
        sale = Sale.objects.create()
        sale_line = SaleLine.objects.create(
            sale=sale,
            item=item,
            gold_price_per_gram=Decimal("1000.00"),
            making_charge_per_gram=Decimal("0.00"),
            quantity=1,
        )
        sale.post_to_ledger()
        sale.reverse(user=self.user, reason="Customer sale entered incorrectly")
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)

        purchase.reverse(user=self.user, reason="Supplier purchase entered incorrectly")

        purchase.refresh_from_db()
        line.refresh_from_db()
        item.refresh_from_db()
        sale_line.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.Status.REVERSED)
        self.assertIsNotNone(purchase.reversal_journal_entry_id)
        self.assertEqual(line.created_item_id, item.pk)
        self.assertEqual(sale_line.item_id, item.pk)
        self.assertEqual(item.quantity, 0)
        self.assertTrue(item.is_archived)
        self.assertEqual(
            JewelryItem.objects.filter(is_archived=False, quantity__gt=0).count(),
            0,
        )

        self.client.force_login(self.user)
        receipt = self.client.get(reverse("sales:receipt", args=[sale.pk]))
        self.assertEqual(receipt.status_code, 200)
        self.assertContains(receipt, "Reversed sale")
        self.assertContains(receipt, item.name)
        new_sale = self.client.get(reverse("sales:new_sale"))
        self.assertNotContains(new_sale, item.name)
        inventory_list = self.client.get(reverse("admin:inventory_jewelryitem_changelist"))
        self.assertContains(inventory_list, "Archived — source purchase reversed")

    def test_reversed_sale_does_not_bypass_purchase_stock_safeguard(self):
        purchase, _, item = self._posted_purchase(quantity=2)
        sale = Sale.objects.create()
        SaleLine.objects.create(
            sale=sale,
            item=item,
            gold_price_per_gram=Decimal("1000.00"),
            making_charge_per_gram=Decimal("0.00"),
            quantity=1,
        )
        sale.post_to_ledger()
        sale.reverse(user=self.user, reason="Customer sale entered incorrectly")
        JewelryItem.objects.filter(pk=item.pk).update(quantity=1)

        with self.assertRaisesMessage(ValidationError, "no longer matches"):
            purchase.reverse(user=self.user, reason="Incorrect supplier")

        purchase.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.Status.POSTED)
        self.assertFalse(item.is_archived)

    def test_reversal_is_blocked_when_stock_no_longer_matches(self):
        purchase, line, item = self._posted_purchase()
        JewelryItem.objects.filter(pk=item.pk).update(quantity=1)

        with self.assertRaisesMessage(ValidationError, "no longer matches"):
            purchase.reverse(user=self.user, reason="Incorrect quantity")

        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.Status.POSTED)
        self.assertIsNone(purchase.reversal_journal_entry_id)

    def test_credit_purchase_reversal_is_blocked_after_supplier_payment(self):
        supplier = Supplier.objects.create(name="Paid Supplier")
        purchase, _, _ = self._posted_purchase(
            supplier=supplier,
            on_credit=True,
            quantity=1,
        )
        payment = Payment.objects.create(
            kind=Payment.Kind.PAY,
            supplier=supplier,
            amount=Decimal("100.00"),
        )
        payment.post_to_ledger()

        with self.assertRaisesMessage(ValidationError, "supplier payment"):
            purchase.reverse(user=self.user, reason="Wrong credit purchase")

        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.Status.POSTED)

    def test_unpaid_credit_reversal_clears_supplier_balance(self):
        supplier = Supplier.objects.create(name="Unpaid Supplier")
        purchase, _, _ = self._posted_purchase(
            supplier=supplier,
            on_credit=True,
            quantity=1,
        )
        self.assertEqual(
            Payment.supplier_balance(supplier)[2],
            purchase.total,
        )

        purchase.reverse(user=self.user, reason="Supplier invoice cancelled")

        billed, paid, outstanding = Payment.supplier_balance(supplier)
        self.assertEqual(billed, Decimal("0.00"))
        self.assertEqual(paid, Decimal("0.00"))
        self.assertEqual(outstanding, Decimal("0.00"))

    def test_admin_requires_reason_and_completes_reversal(self):
        purchase, _, _ = self._posted_purchase()
        self.client.force_login(self.user)
        change_url = reverse("admin:purchases_purchase_change", args=[purchase.pk])
        reverse_url = reverse("admin:purchases_purchase_reverse", args=[purchase.pk])

        change_page = self.client.get(change_url)
        self.assertContains(change_page, "Reverse purchase")
        confirmation = self.client.get(reverse_url)
        self.assertContains(confirmation, f"Reverse Purchase #{purchase.pk}")
        self.assertContains(confirmation, "Reversal reason")

        missing_reason = self.client.post(reverse_url, {"reason": ""})
        self.assertEqual(missing_reason.status_code, 200)
        self.assertContains(missing_reason, "A reversal reason is required")

        response = self.client.post(
            reverse_url,
            {"reason": "Duplicate admin entry"},
            follow=True,
        )
        self.assertContains(response, "Inventory and ledger were updated")
        self.assertNotContains(response, "Reverse purchase")
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.Status.REVERSED)
        self.assertEqual(purchase.reversal_reason, "Duplicate admin entry")

    def test_admin_reversal_requires_purchase_change_permission(self):
        purchase, _, _ = self._posted_purchase()
        viewer = get_user_model().objects.create_user(
            username="purchase-viewer",
            password="test-password",
            is_staff=True,
        )
        viewer.user_permissions.add(Permission.objects.get(
            content_type__app_label="purchases",
            codename="view_purchase",
        ))
        self.client.force_login(viewer)

        reverse_url = reverse("admin:purchases_purchase_reverse", args=[purchase.pk])
        self.assertEqual(self.client.get(reverse_url).status_code, 403)

    def test_database_rejects_reversed_status_without_audit_fields(self):
        purchase, _, _ = self._posted_purchase()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Purchase.objects.filter(pk=purchase.pk).update(
                    status=Purchase.Status.REVERSED,
                )


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
    def _posted_purchase_with_payment_method(self, payment_method, *, on_credit=False):
        supplier = Supplier.objects.create(
            name=f"{payment_method} method supplier {Supplier.objects.count()}",
        )
        purchase = Purchase.objects.create(
            supplier=supplier,
            on_credit=on_credit,
            payment_method=payment_method,
        )
        PurchaseLine.objects.create(
            purchase=purchase,
            name=f"{payment_method} payment ring",
            karat=21,
            weight_grams=Decimal("2.000"),
            raw_gold_price_per_gram=Decimal("500.00"),
            craftsmanship_per_gram=Decimal("0.00"),
            stamp_charge=Decimal("0.00"),
            quantity=1,
        )
        purchase.post_to_ledger()
        purchase.refresh_from_db()
        return purchase

    def test_each_immediate_payment_method_posts_to_its_own_account(self):
        expected_accounts = {
            Purchase.PaymentMethod.CASH: "1011",
            Purchase.PaymentMethod.BANK: "1021",
            Purchase.PaymentMethod.OTHER: "1025",
        }

        for payment_method, account_code in expected_accounts.items():
            with self.subTest(payment_method=payment_method):
                purchase = self._posted_purchase_with_payment_method(payment_method)
                credit_lines = purchase.journal_entry.lines.filter(credit__gt=0)
                self.assertEqual(credit_lines.count(), 1)
                self.assertEqual(credit_lines.get().account.code, account_code)
                self.assertIn(
                    purchase.get_payment_method_display(),
                    purchase.journal_entry.description,
                )

    def test_credit_purchase_posts_to_supplier_payable_regardless_of_method(self):
        purchase = self._posted_purchase_with_payment_method(
            Purchase.PaymentMethod.BANK,
            on_credit=True,
        )

        credit_line = purchase.journal_entry.lines.get(credit__gt=0)
        self.assertEqual(credit_line.account.code, "2011")
        self.assertIn("On credit", purchase.journal_entry.description)

    def test_database_rejects_unknown_purchase_payment_method(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Purchase.objects.bulk_create([
                    Purchase(payment_method="uncontrolled-method"),
                ])

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
        self.assertContains(page, 'name="payment_method"')
        self.assertContains(page, '<option value="cash">Cash</option>', html=True)
        self.assertContains(page, '<option value="bank">Bank</option>', html=True)
        self.assertContains(page, '<option value="other">Other</option>', html=True)
        self.assertContains(page, 'name="raw_gold_price"')
        self.assertContains(page, 'name="craftsmanship"')
        self.assertContains(page, 'name="stamp"')
        self.assertNotContains(page, 'name="cost"')

        response = self.client.post(reverse("purchases:new_purchase"), {
            "payment_method": "bank",
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
        self.assertEqual(line.purchase.payment_method, Purchase.PaymentMethod.BANK)
        self.assertEqual(
            line.purchase.journal_entry.lines.get(credit__gt=0).account.code,
            "1021",
        )

    def test_purchase_page_rejects_unknown_payment_method(self):
        user = get_user_model().objects.create_user("payment-method-user", password="test")
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label="purchases",
            codename="add_purchase",
        ))
        self.client.force_login(user)

        response = self.client.post(reverse("purchases:new_purchase"), {
            "payment_method": "crypto",
            "barcode": ["METHOD-001"],
            "name": ["Controlled payment ring"],
            "category": ["ring"],
            "karat": ["21"],
            "weight": ["2.000"],
            "stone": [""],
            "location": ["safe"],
            "raw_gold_price": ["500.00"],
            "craftsmanship": ["0.00"],
            "stamp": ["0.00"],
            "qty": ["1"],
        }, follow=True)

        self.assertContains(response, "Choose a valid payment method")
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertEqual(PurchaseLine.objects.count(), 0)
        self.assertEqual(JewelryItem.objects.count(), 0)


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
        Purchase.objects.filter(pk=purchase.pk).update(
            journal_entry=purchase_entry,
            status=Purchase.Status.POSTED,
        )
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
        Purchase.objects.filter(pk=purchase.pk).update(
            journal_entry=purchase_entry,
            status=Purchase.Status.POSTED,
        )

        sale = self._sale_one(item)
        sale_entry = JournalEntry.objects.create(description="Sale test")
        Sale.objects.filter(pk=sale.pk).update(
            journal_entry=sale_entry,
            status=Sale.Status.POSTED,
        )

        JournalEntry.objects.filter(pk__in=[purchase_entry.pk, sale_entry.pk]).delete()

        self.assertFalse(JournalEntry.objects.filter(
            pk__in=[purchase_entry.pk, sale_entry.pk]
        ).exists())
        self.assertFalse(Sale.objects.filter(pk=sale.pk).exists())
        self.assertFalse(Purchase.objects.filter(pk=purchase.pk).exists())
        self.assertFalse(PurchaseLine.objects.filter(pk=line.pk).exists())
        self.assertFalse(JewelryItem.objects.filter(pk=item.pk).exists())
