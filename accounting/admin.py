from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from config.admin_controls import ProtectedFromAdminDeletionMixin

from .models import Account, JournalEntry, JournalLine


@admin.register(Account)
class AccountAdmin(ProtectedFromAdminDeletionMixin, admin.ModelAdmin):
    list_display = ("code", "name", "type", "is_group", "parent", "balance_display")
    list_filter = ("type", "is_group")
    search_fields = ("code", "name")

    @admin.display(description="Balance (EGP)")
    def balance_display(self, obj):
        return f"{obj.balance:,.2f}"


class JournalLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return

        active_forms = [
            form for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        if len(active_forms) < 2:
            raise ValidationError("A journal entry must contain at least two posting lines.")

        total_debit = 0
        total_credit = 0
        for row_number, form in enumerate(active_forms, start=1):
            account = form.cleaned_data.get("account")
            if account is not None and account.is_group:
                raise ValidationError(
                    f"{account} is a heading, not a postable account. "
                    f"Choose one of the detail accounts beneath it."
                )
            debit = form.cleaned_data.get("debit") or 0
            credit = form.cleaned_data.get("credit") or 0
            if (debit > 0) == (credit > 0):
                raise ValidationError(
                    f"Line {row_number} must have a positive amount on exactly one side."
                )
            total_debit += debit
            total_credit += credit
        if total_debit <= 0 or total_debit != total_credit:
            raise ValidationError(
                f"Not balanced: debits ({total_debit}) must equal credits ({total_credit}) "
                f"and be greater than zero."
            )

class JournalLineInline(admin.TabularInline):
    model = JournalLine
    formset = JournalLineFormSet
    extra = 2


@admin.register(JournalEntry)
class JournalEntryAdmin(ProtectedFromAdminDeletionMixin, admin.ModelAdmin):
    inlines = [JournalLineInline]
    list_display = ("id", "date", "description", "total_display")
    readonly_fields = ("created_at",)

    def has_change_permission(self, request, obj=None):
        # An existing entry is posted history. Corrections require a new entry.
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)

    @admin.display(description="Total debits (EGP)")
    def total_display(self, obj):
        return f"{obj.total_debits:,.2f}"
