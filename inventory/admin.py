from django.contrib import admin
from .models import JewelryItem


@admin.register(JewelryItem)
class JewelryItemAdmin(admin.ModelAdmin):
    list_display = ("name", "barcode", "category", "karat", "weight_grams", "location", "cost_price", "quantity")
    list_filter = ("location", "category", "karat")
    list_editable = ("location",)
    search_fields = ("barcode", "name", "stone_details")

    def has_add_permission(self, request):
        return False