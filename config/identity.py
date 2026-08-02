import re

from django.core.exceptions import ValidationError


def normalize_name(value):
    return " ".join((value or "").split())


def normalize_phone(value):
    return re.sub(r"[\s\-()]", "", value or "")


def normalize_email(value):
    return (value or "").strip().lower()


def normalize_party(instance):
    instance.name = normalize_name(instance.name)
    instance.phone = normalize_phone(instance.phone)
    instance.email = normalize_email(instance.email)


def validate_party_duplicates(instance, label):
    queryset = type(instance).objects.exclude(pk=instance.pk)
    errors = {}

    if instance.name and queryset.filter(name__iexact=instance.name).exists():
        errors["name"] = f"A {label} with this name already exists."
    if instance.phone and queryset.filter(phone=instance.phone).exists():
        errors["phone"] = f"A {label} with this phone number already exists."
    if instance.email and queryset.filter(email__iexact=instance.email).exists():
        errors["email"] = f"A {label} with this email address already exists."

    if errors:
        raise ValidationError(errors)
