from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import Customer


class CustomerDuplicateTests(TestCase):
    def test_customer_identity_is_normalized_before_save(self):
        customer = Customer.objects.create(
            name="  Ahmed   Mohamed  ",
            phone="0109 350-7625",
            email="  TEST@Yahoo.COM ",
        )

        self.assertEqual(customer.name, "Ahmed Mohamed")
        self.assertEqual(customer.phone, "01093507625")
        self.assertEqual(customer.email, "test@yahoo.com")

    def test_duplicate_name_phone_or_email_is_rejected(self):
        Customer.objects.create(
            name="Ahmed Mohamed",
            phone="01093507625",
            email="test@yahoo.com",
        )

        duplicates = [
            Customer(name="  AHMED   MOHAMED  "),
            Customer(name="Different Name", phone="0109 350-7625"),
            Customer(name="Another Name", email="TEST@YAHOO.COM"),
        ]
        for duplicate in duplicates:
            with self.subTest(customer=duplicate.name):
                with self.assertRaises(ValidationError):
                    duplicate.save()

    def test_database_constraint_catches_bypassed_duplicate(self):
        Customer.objects.create(name="Database Customer")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Customer.objects.bulk_create([Customer(name=" database customer ")])

    def test_new_customer_page_shows_duplicate_error(self):
        Customer.objects.create(name="Existing Customer")
        user = get_user_model().objects.create_user("customer-clerk", password="test")
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label="customers",
            codename="add_customer",
        ))
        self.client.force_login(user)

        response = self.client.post(reverse("customers:new_customer"), {
            "name": " existing   customer ",
        }, follow=True)

        self.assertContains(response, "A customer with this name already exists.")
        self.assertEqual(Customer.objects.count(), 1)
