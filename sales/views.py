from decimal import Decimal

from django.shortcuts import render, redirect
from django.contrib import messages

from inventory.models import JewelryItem
from customers.models import Customer
from .models import Sale, SaleLine


def new_sale(request):
    if request.method == "POST":
        sale = Sale.objects.create(
            customer_id=request.POST.get("customer") or None,
            discount=Decimal(request.POST.get("discount") or 0),
        )
        SaleLine.objects.create(
            sale=sale,
            item_id=request.POST.get("item"),
            gold_price_per_gram=Decimal(request.POST.get("gold") or 0),
            making_charge_per_gram=Decimal(request.POST.get("making") or 0),
            quantity=int(request.POST.get("qty") or 1),
        )
        messages.success(request, f"Sale #{sale.pk} saved — total {sale.total:,.2f} EGP")
        return redirect("sales:new_sale")

    items = JewelryItem.objects.all()
    customers = Customer.objects.all()
    return render(request, "sales/new_sale.html", {"items": items, "customers": customers})