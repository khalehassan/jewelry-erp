import csv
import io
from decimal import Decimal

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction

from purchases.models import Purchase, PurchaseLine
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

        # Every import becomes ONE "opening stock" purchase. The PurchaseLine
        # signal creates the jewelry items, so deleting this purchase later
        # removes the items and the journal entry together.
        with transaction.atomic():
            batch = Purchase.objects.create(is_opening=True)

            for row_num, raw in enumerate(reader, start=2):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
                if not row.get("name") and not row.get("barcode"):
                    continue
                try:
                    PurchaseLine.objects.create(
                        purchase=batch,
                        barcode=row.get("barcode") or "",
                        name=row.get("name") or "Unnamed",
                        category=(row.get("category") or "other").lower(),
                        karat=int(row.get("karat") or "21"),
                        weight_grams=Decimal(row.get("weight_grams") or "0"),
                        stone_details=row.get("stone_details") or "",
                        location=(row.get("location") or "safe").lower(),
                        unit_cost=Decimal(row.get("cost_price") or "0"),
                        quantity=int(row.get("quantity") or "1"),
                    )
                    created += 1
                except Exception as e:
                    errors.append(f"Row {row_num}: {e}")

            if created:
                batch.post_to_ledger()
            else:
                batch.delete()

        if created:
            messages.success(
                request,
                f"Imported {created} item(s) as Opening stock #{batch.pk}. "
                f"Delete that purchase in Admin → Purchases to undo the whole batch."
            )
        else:
            messages.error(request, "No usable rows found in that file.")
        for err in errors[:20]:
            messages.error(request, err)
        return redirect("inventory:import_stock")

    batches = (
        Purchase.objects.filter(is_opening=True)
        .prefetch_related("lines")
        .order_by("-created_at")[:10]
    )
    imports = [{
        "id": b.pk,
        "created_at": b.created_at,
        "count": b.lines.count(),
        "total": f"{b.total:,.2f}",
    } for b in batches]

    return render(request, "inventory/import_stock.html", {"imports": imports})
