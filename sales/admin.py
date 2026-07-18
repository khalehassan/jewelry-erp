from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from .models import Sale, SaleLine


class SaleLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue
            item = form.cleaned_data.get("item")
            qty = form.cleaned_data.get("quantity") or 0
            if item and qty > item.quantity:
                raise ValidationError(f"Not enough stock for {item.name}: only {item.quantity} available.")


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    formset = SaleLineFormSet
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
    list_display = ("id", "customer", "on_credit", "created_at", "total_display", "receipt_link")
    list_filter = ("customer", "on_credit")
    readonly_fields = ("subtotal_display", "total_display", "created_at", "journal_entry")

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.post_to_ledger()

    @admin.display(description="Receipt")
    def receipt_link(self, obj):
        if obj.pk:
            return format_html('<a href="/sale/{}/receipt/" target="_blank">Print</a>', obj.pk)
        return "—"

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