from django.contrib import admin
from .models import Sale, SaleLine


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 1
    readonly_fields = ("line_total_display",)

    @admin.display(description="Line total (EGP)")
    def line_total_display(self, obj):
        if obj.pk is None:
            return "—"
        return f"{obj.line_total:,.2f}"


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    inlines = [SaleLineInline]
    list_display = ("id", "customer", "on_credit", "created_at", "total_display")
    list_filter = ("customer", "on_credit")
    readonly_fields = ("subtotal_display", "total_display", "created_at")

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.post_to_ledger()

    @admin.display(description="Subtotal (EGP)")
    def subtotal_display(self, obj):
        if obj.pk is None:
            return "—"
        return f"{obj.subtotal:,.2f}"

    @admin.display(description="Total (EGP)")
    def total_display(self, obj):
        if obj.pk is None:
            return "—"
        return f"{obj.total:,.2f}"