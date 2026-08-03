from django import forms
from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from config.admin_controls import ProtectedFromAdminDeletionMixin

from .models import Supplier, Purchase, PurchaseLine


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email")
    search_fields = ("name", "phone", "email")


class PurchaseLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active_forms = [
            form for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        if not active_forms:
            raise ValidationError("A purchase must contain at least one item.")


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    formset = PurchaseLineFormSet
    extra = 1
    fields = (
        "barcode", "name", "category", "karat", "weight_grams",
        "stone_details", "location", "raw_gold_price_per_gram",
        "craftsmanship_per_gram", "stamp_charge", "quantity",
        "line_total_display",
    )
    readonly_fields = ("line_total_display",)

    @admin.display(description="Line total (EGP)")
    def line_total_display(self, obj):
        if obj.pk is None:
            return "—"
        return f"{obj.line_total:,.2f}"


@admin.register(Purchase)
class PurchaseAdmin(ProtectedFromAdminDeletionMixin, admin.ModelAdmin):
    change_form_template = "admin/purchases/purchase/change_form.html"
    inlines = [PurchaseLineInline]
    list_display = (
        "id", "status", "supplier", "payment_method_display", "is_opening",
        "on_credit", "created_at", "total_display",
    )
    list_filter = (
        "status", "payment_method", "supplier", "on_credit", "is_opening",
    )
    readonly_fields = (
        "status", "total_display", "created_at", "journal_entry",
        "reversal_journal_entry", "reversed_at", "reversed_by",
        "reversal_reason",
    )

    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/reverse/",
                self.admin_site.admin_view(self.reverse_purchase_view),
                name="purchases_purchase_reverse",
            ),
        ]
        return custom_urls + super().get_urls()

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = dict(extra_context or {})
        purchase = self.get_object(request, object_id) if object_id else None
        extra_context["show_reverse_button"] = bool(
            purchase
            and purchase.status == Purchase.Status.POSTED
            and request.user.has_perm("purchases.change_purchase")
        )
        if purchase:
            extra_context["reverse_purchase_url"] = reverse(
                "admin:purchases_purchase_reverse",
                args=[purchase.pk],
            )
        return super().changeform_view(
            request,
            object_id,
            form_url,
            extra_context=extra_context,
        )

    def reverse_purchase_view(self, request, object_id):
        if not request.user.has_perm("purchases.change_purchase"):
            raise PermissionDenied
        purchase = self.get_object(request, object_id)
        if purchase is None:
            raise Http404("Purchase does not exist")

        error_message = ""
        reason = (request.POST.get("reason") or "").strip()
        if request.method == "POST":
            try:
                purchase.reverse(user=request.user, reason=reason)
            except ValidationError as error:
                error_message = " ".join(error.messages)
            else:
                self.message_user(
                    request,
                    f"Purchase #{purchase.pk} was reversed. Inventory and ledger were updated.",
                    level=messages.SUCCESS,
                )
                return redirect("admin:purchases_purchase_change", purchase.pk)

        context = {
            **self.admin_site.each_context(request),
            "title": f"Reverse Purchase #{purchase.pk}",
            "opts": self.model._meta,
            "original": purchase,
            "purchase": purchase,
            "reason": reason,
            "error_message": error_message,
            "change_url": reverse("admin:purchases_purchase_change", args=[purchase.pk]),
        }
        return TemplateResponse(
            request,
            "admin/purchases/purchase/reverse_confirmation.html",
            context,
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.post_to_ledger()

    def has_change_permission(self, request, obj=None):
        # A posted purchase is locked — the admin shows it read-only instead.
        if obj is not None and obj.journal_entry_id:
            return False
        return super().has_change_permission(request, obj)

    @admin.display(description="Payment method", ordering="payment_method")
    def payment_method_display(self, obj):
        if obj.is_opening:
            return "Opening balance"
        if obj.on_credit:
            return "On credit"
        return obj.get_payment_method_display()

    @admin.display(description="Total (EGP)")
    def total_display(self, obj):
        if obj.pk is None:
            return "—"
        return f"{obj.total:,.2f}"
