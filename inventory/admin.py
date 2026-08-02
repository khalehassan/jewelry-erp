from django.contrib import admin

from config.admin_controls import ProtectedFromAdminDeletionMixin

from .models import JewelryItem


@admin.register(JewelryItem)
class JewelryItemAdmin(ProtectedFromAdminDeletionMixin, admin.ModelAdmin):
    list_display = ("name", "barcode", "category", "karat", "weight_grams", "location", "cost_price", "quantity")
    list_filter = ("location", "category", "karat")
    search_fields = ("barcode", "name", "stone_details")

    def has_add_permission(self, request):
        # Stock must originate from a purchase or the validated import workflow.
        return False

    def has_change_permission(self, request, obj=None):
        # Quantity, weight and cost must only move through business transactions.
        return False
