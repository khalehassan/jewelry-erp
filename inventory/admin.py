from django.contrib import admin

from config.admin_controls import ProtectedFromAdminDeletionMixin

from .models import JewelryItem


@admin.register(JewelryItem)
class JewelryItemAdmin(ProtectedFromAdminDeletionMixin, admin.ModelAdmin):
    list_display = (
        "name", "barcode", "category", "karat", "weight_grams", "location",
        "cost_price", "quantity", "stock_status",
    )
    list_filter = ("is_archived", "location", "category", "karat")
    search_fields = ("barcode", "name", "stone_details")

    @admin.display(description="Stock status", ordering="is_archived")
    def stock_status(self, obj):
        if obj.is_archived:
            return "Archived — source purchase reversed"
        if obj.quantity == 0:
            return "Out of stock"
        return "Available"

    def has_add_permission(self, request):
        # Stock must originate from a purchase or the validated import workflow.
        return False

    def has_change_permission(self, request, obj=None):
        # Quantity, weight and cost must only move through business transactions.
        return False
