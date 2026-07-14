from decimal import Decimal

from django.contrib import admin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "sales_count", "total_spent")
    search_fields = ("name", "phone", "email")

    @admin.display(description="Purchases")
    def sales_count(self, obj):
        return obj.sales.count()

    @admin.display(description="Total spent (EGP)")
    def total_spent(self, obj):
        total = sum((sale.total for sale in obj.sales.all()), Decimal("0.00"))
        return f"{total:,.2f}"