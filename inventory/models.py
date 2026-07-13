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

    name = models.CharField(max_length=120)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.RING)
    karat = models.IntegerField(choices=Karat.choices, default=Karat.K21)
    weight_grams = models.DecimalField(max_digits=8, decimal_places=3)
    stone_details = models.CharField(max_length=200, blank=True)
    making_charge_per_gram = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} — {self.karat}K, {self.weight_grams}g"

    @property
    def calculated_price(self):
        latest_rate = GoldRate.objects.filter(karat=self.karat).order_by("-recorded_at").first()
        if latest_rate is None:
            return None
        return self.weight_grams * (latest_rate.price_per_gram + self.making_charge_per_gram)


class GoldRate(models.Model):
    karat = models.IntegerField(choices=JewelryItem.Karat.choices)
    price_per_gram = models.DecimalField(max_digits=10, decimal_places=2)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-recorded_at"]

    def __str__(self):
        return f"{self.karat}K — {self.price_per_gram} EGP/g @ {self.recorded_at:%Y-%m-%d %H:%M}"