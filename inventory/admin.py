from django.contrib import admin
from .models import JewelryItem


@admin.register(JewelryItem)
class JewelryItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "karat", "weight_grams", "cost_price", "quantity")
    list_filter = ("category", "karat")
    search_fields = ("name", "stone_details")

    def has_add_permission(self, request):
        return False