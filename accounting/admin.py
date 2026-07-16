from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from .models import Account, JournalEntry, JournalLine


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "type", "balance_display")
    list_filter = ("type",)
    search_fields = ("code", "name")

    @admin.display(description="Balance (EGP)")
    def balance_display(self, obj):
        return f"{obj.balance:,.2f}"


class JournalLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        total_debit = 0
        total_credit = 0
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue
            total_debit += form.cleaned_data.get("debit") or 0
            total_credit += form.cleaned_data.get("credit") or 0
        if total_debit != total_credit:
            raise ValidationError(
                f"Not balanced: debits ({total_debit}) must equal credits ({total_credit})."
            )

class JournalLineInline(admin.TabularInline):
    model = JournalLine
    formset = JournalLineFormSet
    extra = 2


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    inlines = [JournalLineInline]
    list_display = ("id", "date", "description", "total_display")
    readonly_fields = ("created_at",)

    @admin.display(description="Total debits (EGP)")
    def total_display(self, obj):
        return f"{obj.total_debits:,.2f}"