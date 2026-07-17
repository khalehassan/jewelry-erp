from decimal import Decimal

from django.shortcuts import render, redirect
from django.contrib import messages

from inventory.models import JewelryItem
from .models import Supplier, Purchase, PurchaseLine


def new_purchase(request):
    if request.method == "POST":
        purchase = Purchase.objects.create(
            supplier_id=request.POST.get("supplier") or None,
            on_credit=bool(request.POST.get("on_credit")),
        )
        barcodes = request.POST.getlist("barcode")
        names = request.POST.getlist("name")
        categories = request.POST.getlist("category")
        karats = request.POST.getlist("karat")
        weights = request.POST.getlist("weight")
        stones = request.POST.getlist("stone")
        locations = request.POST.getlist("location")
        costs = request.POST.getlist("cost")
        qtys = request.POST.getlist("qty")

        for barcode, name, category, karat, weight, stone, location, cost, qty in zip(
            barcodes, names, categories, karats, weights, stones, locations, costs, qtys
        ):
            if not name.strip():
                continue  # skip blank rows
            PurchaseLine.objects.create(
                purchase=purchase,
                barcode=barcode.strip(),
                name=name.strip(),
                category=category,
                karat=int(karat or 21),
                weight_grams=Decimal(weight or 0),
                stone_details=stone.strip(),
                location=location,
                unit_cost=Decimal(cost or 0),
                quantity=int(qty or 1),
            )

        purchase.post_to_ledger()
        messages.success(request, f"Purchase #{purchase.pk} saved — total {purchase.total:,.2f} EGP")
        return redirect("purchases:new_purchase")

    return render(request, "purchases/new_purchase.html", {
        "suppliers": Supplier.objects.all(),
        "categories": JewelryItem.Category.choices,
        "karats": JewelryItem.Karat.choices,
        "locations": JewelryItem.Location.choices,
    })