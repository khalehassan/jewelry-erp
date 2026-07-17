from django.db import models
from django.utils import timezone


class JewelryItem(models.Model):
    class Category(models.TextChoices):
        RING = "ring", "Ring"
        NECKLACE = "necklace", "Necklace"
        BRACELET = "bracelet", "Bracelet"
        EARRING = "earring", "Earring"
        CHAIN = "chain", "Chain"
        PENDANT = "pendant", "Pendant"
        OTHER = "other", "Other"

    class Karat(models.IntegerChoices):
        K18 = 18, "18K"
        K21 = 21, "21K"
        K24 = 24, "24K"

    class Location(models.TextChoices):
        SAFE = "safe", "Safe"
        SHOWCASE = "showcase", "Showcase"

    name = models.CharField(max_length=120)
    barcode = models.CharField(max_length=50, unique=True, null=True, blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.RING)
    karat = models.IntegerField(choices=Karat.choices, default=Karat.K21)
    weight_grams = models.DecimalField(max_digits=8, decimal_places=3)
    stone_details = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=20, choices=Location.choices, default=Location.SAFE)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} — {self.karat}K, {self.weight_grams}g"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.barcode:
            candidate = f"JW{self.pk:06d}"
            n = 0
            while JewelryItem.objects.exclude(pk=self.pk).filter(barcode=candidate).exists():
                n += 1
                candidate = f"JW{self.pk:06d}-{n}"
            self.barcode = candidate
            super().save(update_fields=["barcode"])

    @property
    def gold_value(self):
        latest_rate = GoldRate.objects.filter(karat=self.karat).order_by("-recorded_at").first()
        if latest_rate is None:
            return None
        return self.weight_grams * latest_rate.price_per_gram


class GoldRate(models.Model):
    karat = models.IntegerField(choices=JewelryItem.Karat.choices)
    price_per_gram = models.DecimalField(max_digits=10, decimal_places=2)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-recorded_at"]

    def __str__(self):
        return f"{self.karat}K — {self.price_per_gram} EGP/g @ {self.recorded_at:%Y-%m-%d %H:%M}"