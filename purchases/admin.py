from django.contrib import admin
from .models import Supplier, Purchase, PurchaseLine


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email")
    search_fields = ("name", "phone", "email")


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    extra = 1
    fields = ("barcode", "name", "category", "karat", "weight_grams", "stone_details", "location", "unit_cost", "quantity", "line_total_display")
    readonly_fields = ("line_total_display",)

    @admin.display(description="Line total (EGP)")
    def line_total_display(self, obj):
        if obj.pk is None:
            return "—"
        return f"{obj.line_total:,.2f}"


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    inlines = [PurchaseLineInline]
    list_display = ("id", "supplier", "on_credit", "created_at", "total_display")
    list_filter = ("supplier", "on_credit")
    readonly_fields = ("total_display", "created_at", "journal_entry")

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.post_to_ledger()

    @admin.display(description="Total (EGP)")
    def total_display(self, obj):
        if obj.pk is None:
            return "—"
        return f"{obj.total:,.2f}"