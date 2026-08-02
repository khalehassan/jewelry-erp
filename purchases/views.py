from decimal import Decimal, InvalidOperation

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

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
        barcodes = request.POST.getlist("barcode")
        names = request.POST.getlist("name")
        categories = request.POST.getlist("category")
        karats = request.POST.getlist("karat")
        weights = request.POST.getlist("weight")
        stones = request.POST.getlist("stone")
        locations = request.POST.getlist("location")
        costs = request.POST.getlist("cost")
        qtys = request.POST.getlist("qty")

        lines = []
        errors = []
        for row_number, values in enumerate(zip(
            barcodes, names, categories, karats, weights, stones, locations, costs, qtys
        ), start=1):
            barcode, name, category, karat, weight, stone, location, cost, qty = values
            name = name.strip()
            has_input = any((barcode.strip(), name, weight.strip(), stone.strip(), cost.strip()))
            if not name:
                if has_input:
                    errors.append(f"Item {row_number}: Name is required.")
                continue
            try:
                parsed_weight = Decimal(weight)
                parsed_cost = Decimal(cost)
                parsed_quantity = int(qty)
                parsed_karat = int(karat)
            except (InvalidOperation, TypeError, ValueError):
                errors.append(f"Item {row_number}: Enter valid numbers for weight, unit cost, and quantity.")
                continue

            if not parsed_weight.is_finite() or parsed_weight <= 0:
                errors.append(f"Item {row_number}: Weight must be greater than zero.")
            if not parsed_cost.is_finite() or parsed_cost <= 0:
                errors.append(f"Item {row_number}: Unit cost must be greater than zero.")
            if parsed_quantity <= 0:
                errors.append(f"Item {row_number}: Quantity must be at least 1.")

            lines.append({
                "barcode": barcode.strip(),
                "name": name,
                "category": category,
                "karat": parsed_karat,
                "weight_grams": parsed_weight,
                "stone_details": stone.strip(),
                "location": location,
                "unit_cost": parsed_cost,
                "quantity": parsed_quantity,
            })

        if not lines and not errors:
            errors.append("A purchase must contain at least one item.")
        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect("purchases:new_purchase")

        try:
            with transaction.atomic():
                purchase = Purchase.objects.create(
                    supplier_id=request.POST.get("supplier") or None,
                    on_credit=bool(request.POST.get("on_credit")),
                )
                for line in lines:
                    PurchaseLine.objects.create(purchase=purchase, **line)
                purchase.post_to_ledger()
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("purchases:new_purchase")
        except IntegrityError:
            messages.error(request, "The purchase could not be saved because one of its values is invalid.")
            return redirect("purchases:new_purchase")

        messages.success(request, f"Purchase #{purchase.pk} saved — total {purchase.total:,.2f} EGP")
        return redirect("purchases:new_purchase")

    return render(request, "purchases/new_purchase.html", {
        "suppliers": Supplier.objects.all(),
        "categories": JewelryItem.Category.choices,
        "karats": JewelryItem.Karat.choices,
        "locations": JewelryItem.Location.choices,
    })
