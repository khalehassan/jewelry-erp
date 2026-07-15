from datetime import date
from decimal import Decimal

from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone

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


def dashboard(request):
    today = timezone.localdate()

    # Today's sales
    todays_sales = Sale.objects.filter(created_at__date=today)
    todays_count = todays_sales.count()
    todays_revenue = sum((s.total for s in todays_sales), Decimal("0.00"))

    # Today's profit = revenue - what those items cost you
    todays_cost = Decimal("0.00")
    for s in todays_sales:
        for line in s.lines.all():
            todays_cost += line.item.cost_price * line.quantity
    todays_profit = todays_revenue - todays_cost

    # Total stock value at the latest gold rate
    stock_value = Decimal("0.00")
    for item in JewelryItem.objects.all():
        value = item.gold_value
        if value is not None:
            stock_value += value * item.quantity

    # Best sellers (by quantity sold, all time)
    sold = {}
    for line in SaleLine.objects.all():
        sold[line.item.name] = sold.get(line.item.name, 0) + line.quantity
    best_sellers = sorted(sold.items(), key=lambda pair: pair[1], reverse=True)[:5]

    return render(request, "sales/dashboard.html", {
        "today": today,
        "todays_count": todays_count,
        "todays_revenue": todays_revenue,
        "todays_profit": todays_profit,
        "stock_value": stock_value,
        "best_sellers": best_sellers,
    })