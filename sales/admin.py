from django import forms
from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from config.admin_controls import ProtectedFromAdminDeletionMixin

from .models import Sale, SaleLine


class SaleLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return

        active_forms = [
            form for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        if not active_forms:
            raise ValidationError("A sale must contain at least one item.")

        selected_items = {}
        subtotal = 0
        for form in active_forms:
            item = form.cleaned_data.get("item")
            qty = form.cleaned_data.get("quantity") or 0
            if item and item.pk in selected_items:
                raise ValidationError(
                    f"{item.name} appears more than once. Combine it into one line with the total quantity."
                )
            if item:
                selected_items[item.pk] = item
            if item and qty > item.quantity:
                raise ValidationError(f"Not enough stock for {item.name}: only {item.quantity} available.")
            gold = form.cleaned_data.get("gold_price_per_gram") or 0
            making = form.cleaned_data.get("making_charge_per_gram") or 0
            if item:
                subtotal += item.weight_grams * (gold + making) * qty

        discount = self.instance.discount or 0
        if subtotal - discount <= 0:
            raise ValidationError("Sale total must be greater than zero. Reduce the discount.")


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
class SaleAdmin(ProtectedFromAdminDeletionMixin, admin.ModelAdmin):
    change_form_template = "admin/sales/sale/change_form.html"
    inlines = [SaleLineInline]
    list_display = (
        "id", "status", "customer", "on_credit", "created_at", "total_display",
        "receipt_link",
    )
    list_filter = ("status", "customer", "on_credit")
    readonly_fields = (
        "status", "subtotal_display", "total_display", "created_at",
        "journal_entry", "reversal_journal_entry", "reversed_at", "reversed_by",
        "reversal_reason",
    )

    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/reverse/",
                self.admin_site.admin_view(self.reverse_sale_view),
                name="sales_sale_reverse",
            ),
        ]
        return custom_urls + super().get_urls()

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = dict(extra_context or {})
        sale = self.get_object(request, object_id) if object_id else None
        extra_context["show_reverse_button"] = bool(
            sale
            and sale.status == Sale.Status.POSTED
            and request.user.has_perm("sales.change_sale")
        )
        if sale:
            extra_context["reverse_sale_url"] = reverse(
                "admin:sales_sale_reverse",
                args=[sale.pk],
            )
        return super().changeform_view(
            request,
            object_id,
            form_url,
            extra_context=extra_context,
        )

    def reverse_sale_view(self, request, object_id):
        if not request.user.has_perm("sales.change_sale"):
            raise PermissionDenied
        sale = self.get_object(request, object_id)
        if sale is None:
            raise Http404("Sale does not exist")

        error_message = ""
        reason = (request.POST.get("reason") or "").strip()
        if request.method == "POST":
            try:
                sale.reverse(user=request.user, reason=reason)
            except ValidationError as error:
                error_message = " ".join(error.messages)
            else:
                self.message_user(
                    request,
                    f"Sale #{sale.pk} was reversed. Inventory and ledger were updated.",
                    level=messages.SUCCESS,
                )
                return redirect("admin:sales_sale_change", sale.pk)

        context = {
            **self.admin_site.each_context(request),
            "title": f"Reverse Sale #{sale.pk}",
            "opts": self.model._meta,
            "original": sale,
            "sale": sale,
            "reason": reason,
            "error_message": error_message,
            "change_url": reverse("admin:sales_sale_change", args=[sale.pk]),
        }
        return TemplateResponse(
            request,
            "admin/sales/sale/reverse_confirmation.html",
            context,
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.post_to_ledger()

    def has_change_permission(self, request, obj=None):
        # A posted sale is locked — the admin shows it read-only instead.
        if obj is not None and obj.journal_entry_id:
            return False
        return super().has_change_permission(request, obj)

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
