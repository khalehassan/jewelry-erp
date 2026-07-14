from django.contrib import admin
from .models import JewelryItem, GoldRate


@admin.register(JewelryItem)
class JewelryItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "karat", "weight_grams",
                    "gold_value_display", "cost_price", "quantity")
    list_filter = ("category", "karat")
    search_fields = ("name", "stone_details")

    @admin.display(description="Gold value (EGP)")
    def gold_value_display(self, obj):
        value = obj.gold_value
        if value is None:
            return "— set gold rate —"
        return f"{value:,.2f}"


@admin.register(GoldRate)
class GoldRateAdmin(admin.ModelAdmin):
    list_display = ("karat", "price_per_gram", "recorded_at")
    list_filter = ("karat",)