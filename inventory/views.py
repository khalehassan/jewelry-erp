import csv
import io
from decimal import Decimal

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from accounting.services import create_entry
from .models import JewelryItem


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


@require_perm("inventory.add_jewelryitem")
def import_stock(request):
    if request.method == "POST" and request.FILES.get("file"):
        decoded = request.FILES["file"].read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded))
        created = 0
        errors = []

        for row_num, raw in enumerate(reader, start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
            if not row.get("name") and not row.get("barcode"):
                continue
            try:
                cost = Decimal(row.get("cost_price") or "0")
                qty = int(row.get("quantity") or "1")
                item = JewelryItem.objects.create(
                    name=row.get("name") or "Unnamed",
                    barcode=row.get("barcode") or None,
                    category=(row.get("category") or "other").lower(),
                    karat=int(row.get("karat") or "21"),
                    weight_grams=Decimal(row.get("weight_grams") or "0"),
                    stone_details=row.get("stone_details") or "",
                    location=(row.get("location") or "safe").lower(),
                    cost_price=cost,
                    quantity=qty,
                )
                created += 1

                line_cost = cost * qty
                if line_cost > 0:
                    create_entry(
                        timezone.localdate(),
                        f"Opening stock: {item.name} [{item.barcode}]",
                        [("1200", line_cost, Decimal("0.00")),
                         ("3000", Decimal("0.00"), line_cost)],
                    )
            except Exception as e:
                errors.append(f"Row {row_num}: {e}")

        messages.success(request, f"Imported {created} item(s) — each with its own opening entry.")
        for err in errors[:20]:
            messages.error(request, err)
        return redirect("inventory:import_stock")

    return render(request, "inventory/import_stock.html", {})