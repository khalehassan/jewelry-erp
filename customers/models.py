from django.db import models
from django.db.models.functions import Lower, Trim

from config.identity import normalize_party, validate_party_duplicates


class Customer(models.Model):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower(Trim("name")),
                name="customer_name_normalized_unique",
            ),
            models.UniqueConstraint(
                Trim("phone"),
                condition=~models.Q(phone=""),
                name="customer_phone_normalized_unique",
            ),
            models.UniqueConstraint(
                Lower(Trim("email")),
                condition=~models.Q(email=""),
                name="customer_email_normalized_unique",
            ),
        ]

    def clean(self):
        super().clean()
        normalize_party(self)
        validate_party_duplicates(self, "customer")

    def save(self, *args, **kwargs):
        normalize_party(self)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name
