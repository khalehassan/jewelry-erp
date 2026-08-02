from decimal import Decimal

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError

from inventory.models import JewelryItem
from .models import Supplier, Purchase, PurchaseLine


def require_perm(perm):
    def decorator(view):
        @login_required
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perm(perm):
                messages.error(request, "You don't have permission to open that page.")
                return redirect("sales:dashboard")
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


@require_perm("purchases.add_supplier")
def new_supplier(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Supplier name is required.")
            return redirect("purchases:new_supplier")
        supplier = Supplier(
            name=name,
            phone=(request.POST.get("phone") or "").strip(),
            email=(request.POST.get("email") or "").strip(),
            notes=(request.POST.get("notes") or "").strip(),
        )
        try:
            supplier.save()
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("purchases:new_supplier")
        messages.success(request, f"Supplier “{supplier.name}” added.")
        return redirect("purchases:new_supplier")

    return render(request, "purchases/new_supplier.html", {
        "suppliers": Supplier.objects.all().order_by("name"),
    })


@require_perm("purchases.add_purchase")
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
                continue
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
