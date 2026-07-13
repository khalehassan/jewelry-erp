from django.contrib import admin
from .models import JewelryItem, GoldRate


@admin.register(JewelryItem)
class JewelryItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "karat", "weight_grams",
                    "making_charge_per_gram", "calculated_price_display",
                    "selling_price", "quantity")
    list_filter = ("category", "karat")
    search_fields = ("name", "stone_details")

    @admin.display(description="Calculated price (EGP)")
    def calculated_price_display(self, obj):
        price = obj.calculated_price
        if price is None:
            return "— set gold rate —"
        return f"{price:,.2f}"


@admin.register(GoldRate)
class GoldRateAdmin(admin.ModelAdmin):
    list_display = ("karat", "price_per_gram", "recorded_at")
    list_filter = ("karat",)