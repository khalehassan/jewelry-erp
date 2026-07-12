from django.db import models


class JewelryItem(models.Model):
    # Fixed lists the user picks from (like a dropdown)
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

    # The actual fields (the "columns")
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.RING)
    karat = models.IntegerField(choices=Karat.choices, default=Karat.K21)
    weight_grams = models.DecimalField(max_digits=8, decimal_places=3)
    stone_details = models.CharField(max_length=200, blank=True)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} — {self.karat}K, {self.weight_grams}g"