from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounting.models import JournalEntry
from customers.models import Customer
from inventory.models import JewelryItem
from purchases.models import Purchase, PurchaseLine, Supplier
from sales.models import Sale, SaleLine
from .models import Payment


class PaymentTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        cls.customer = Customer.objects.create(name="Credit Customer")
        stock_item = JewelryItem.objects.create(
            name="Credit sale ring",
            category=JewelryItem.Category.RING,
            karat=JewelryItem.Karat.K21,
            weight_grams=Decimal("1.000"),
            location=JewelryItem.Location.SHOWCASE,
            cost_price=Decimal("500.00"),
            quantity=1,
        )
        sale = Sale.objects.create(customer=cls.customer, on_credit=True)
        SaleLine.objects.create(
            sale=sale,
            item=stock_item,
            gold_price_per_gram=Decimal("1000.00"),
            making_charge_per_gram=Decimal("0.00"),
            quantity=1,
        )
        sale.post_to_ledger()

        cls.supplier = Supplier.objects.create(name="Credit Supplier")
        purchase = Purchase.objects.create(supplier=cls.supplier, on_credit=True)
        PurchaseLine.objects.create(
            purchase=purchase,
            name="Credit purchase bracelet",
            category=JewelryItem.Category.BRACELET,
            karat=JewelryItem.Karat.K18,
            weight_grams=Decimal("1.000"),
            unit_cost=Decimal("800.00"),
            quantity=1,
        )
        purchase.post_to_ledger()


class PaymentModelValidationTests(PaymentTestDataMixin, TestCase):
    def test_customer_and_supplier_overpayments_are_rejected(self):
        invalid_payments = [
            Payment(
                kind=Payment.Kind.RECEIVE,
                customer=self.customer,
                amount=Decimal("1000.01"),
            ),
            Payment(
                kind=Payment.Kind.PAY,
                supplier=self.supplier,
                amount=Decimal("800.01"),
            ),
        ]

        for payment in invalid_payments:
            with self.subTest(kind=payment.kind):
                with self.assertRaisesMessage(ValidationError, "outstanding balance"):
                    payment.save()

        self.assertEqual(Payment.objects.count(), 0)

    def test_partial_payment_prevents_later_cumulative_overpayment(self):
        first = Payment.objects.create(
            kind=Payment.Kind.RECEIVE,
            customer=self.customer,
            amount=Decimal("600.00"),
        )
        first.post_to_ledger()

        with self.assertRaisesMessage(ValidationError, "400.00 EGP"):
            Payment.objects.create(
                kind=Payment.Kind.RECEIVE,
                customer=self.customer,
                amount=Decimal("400.01"),
            )

        billed, paid, outstanding = Payment.customer_balance(self.customer)
        self.assertEqual(billed, Decimal("1000.00000"))
        self.assertEqual(paid, Decimal("600.00"))
        self.assertEqual(outstanding, Decimal("400.00000"))
        self.assertEqual(Payment.objects.count(), 1)

    def test_nonpositive_amount_and_wrong_party_are_rejected(self):
        invalid_payments = [
            Payment(kind=Payment.Kind.RECEIVE, customer=self.customer, amount=0),
            Payment(kind=Payment.Kind.PAY, supplier=self.supplier, amount=-1),
            Payment(
                kind=Payment.Kind.RECEIVE,
                customer=self.customer,
                supplier=self.supplier,
                amount=1,
            ),
            Payment(kind=Payment.Kind.PAY, customer=self.customer, amount=1),
        ]

        for payment in invalid_payments:
            with self.subTest(kind=payment.kind, amount=payment.amount):
                with self.assertRaises(ValidationError):
                    payment.save()

        self.assertEqual(Payment.objects.count(), 0)

    def test_database_constraints_reject_bypassed_invalid_records(self):
        invalid_payments = [
            Payment(kind=Payment.Kind.RECEIVE, customer=self.customer, amount=0),
            Payment(
                kind=Payment.Kind.RECEIVE,
                customer=self.customer,
                supplier=self.supplier,
                amount=1,
            ),
        ]

        for payment in invalid_payments:
            with self.subTest(kind=payment.kind, amount=payment.amount):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        Payment.objects.bulk_create([payment])

    def test_ledger_gate_rejects_bypassed_overpayment(self):
        journal_count = JournalEntry.objects.count()
        Payment.objects.bulk_create([
            Payment(
                kind=Payment.Kind.RECEIVE,
                customer=self.customer,
                amount=Decimal("1000.01"),
            )
        ])
        payment = Payment.objects.get()

        with self.assertRaisesMessage(ValidationError, "outstanding balance"):
            payment.post_to_ledger()

        payment.refresh_from_db()
        self.assertIsNone(payment.journal_entry_id)
        self.assertEqual(JournalEntry.objects.count(), journal_count)


class PaymentPageValidationTests(PaymentTestDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = get_user_model().objects.create_user("payment-clerk", password="test")
        cls.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="payments",
            codename="add_payment",
        ))

    def setUp(self):
        self.client.force_login(self.user)

    def test_customer_overpayment_is_rejected_without_posting(self):
        journal_count = JournalEntry.objects.count()
        response = self.client.post(reverse("payments:payments"), {
            "kind": Payment.Kind.RECEIVE,
            "customer": self.customer.pk,
            "amount": "1000.01",
        }, follow=True)

        self.assertContains(response, "outstanding balance of 1,000.00 EGP")
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), journal_count)

    def test_supplier_overpayment_is_rejected_without_posting(self):
        journal_count = JournalEntry.objects.count()
        response = self.client.post(reverse("payments:payments"), {
            "kind": Payment.Kind.PAY,
            "supplier": self.supplier.pk,
            "amount": "800.01",
        }, follow=True)

        self.assertContains(response, "outstanding balance of 800.00 EGP")
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), journal_count)

    def test_exact_customer_receipt_posts_and_settles_balance(self):
        response = self.client.post(reverse("payments:payments"), {
            "kind": Payment.Kind.RECEIVE,
            "customer": self.customer.pk,
            "amount": "1000.00",
        }, follow=True)

        self.assertContains(response, "Received 1,000.00 EGP")
        payment = Payment.objects.get()
        self.assertIsNotNone(payment.journal_entry_id)
        _, paid, outstanding = Payment.customer_balance(self.customer)
        self.assertEqual(paid, Decimal("1000.00"))
        self.assertEqual(outstanding, Decimal("0.00000"))
        self.assertEqual(response.context["customers"], [])

    def test_exact_supplier_payment_posts_and_settles_balance(self):
        response = self.client.post(reverse("payments:payments"), {
            "kind": Payment.Kind.PAY,
            "supplier": self.supplier.pk,
            "amount": "800.00",
        }, follow=True)

        self.assertContains(response, "Paid 800.00 EGP")
        payment = Payment.objects.get()
        self.assertIsNotNone(payment.journal_entry_id)
        _, paid, outstanding = Payment.supplier_balance(self.supplier)
        self.assertEqual(paid, Decimal("800.00"))
        self.assertEqual(outstanding, Decimal("0.00"))
        self.assertEqual(response.context["suppliers"], [])
