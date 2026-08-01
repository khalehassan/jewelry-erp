from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "kind", "customer", "supplier", "amount", "note")
    list_filter = ("kind", "created_at")
    search_fields = ("customer__name", "supplier__name", "note")
    readonly_fields = ("journal_entry",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.post_to_ledger()
