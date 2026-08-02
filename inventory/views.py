import csv
import io
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from purchases.models import Purchase, PurchaseLine
from .models import JewelryItem


REQUIRED_IMPORT_COLUMNS = {
    "barcode",
    "name",
    "category",
    "karat",
    "weight_grams",
    "cost_price",
    "location",
    "quantity",
}


def _parse_import_file(uploaded_file):
    """Validate the complete CSV and return rows safe to write as purchase lines."""
    try:
        decoded = uploaded_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["The file is not a valid UTF-8 CSV. Export it as CSV UTF-8 and try again."]

    try:
        reader = csv.DictReader(io.StringIO(decoded))
        raw_headers = reader.fieldnames
    except csv.Error as error:
        return [], [f"The CSV could not be read: {error}"]

    if not raw_headers:
        return [], ["The CSV is empty or has no header row."]

    headers = [(header or "").strip().lower() for header in raw_headers]
    duplicate_headers = sorted({header for header in headers if headers.count(header) > 1})
    if duplicate_headers:
        return [], [f"Duplicate column header(s): {', '.join(duplicate_headers)}."]

    missing_headers = sorted(REQUIRED_IMPORT_COLUMNS - set(headers))
    if missing_headers:
        return [], [f"Missing required column(s): {', '.join(missing_headers)}."]

    parsed_rows = []
    errors = []
    try:
        csv_rows = list(reader)
    except csv.Error as error:
        return [], [f"The CSV could not be read: {error}"]

    for row_number, raw in enumerate(csv_rows, start=2):
        if None in raw:
            errors.append(f"Row {row_number}: The row has more values than the header row.")
            continue

        row = {
            (key or "").strip().lower(): (value or "").strip()
            for key, value in raw.items()
        }
        if not any(row.values()):
            continue

        row_errors = []
        name = row.get("name", "")
        barcode = row.get("barcode", "")
        category = row.get("category", "").lower()
        location = row.get("location", "").lower()

        if not name:
            row_errors.append("name is required")
        if not category:
            row_errors.append("category is required")
        elif category not in JewelryItem.Category.values:
            row_errors.append(
                f"category must be one of: {', '.join(JewelryItem.Category.values)}"
            )
        if not location:
            row_errors.append("location is required")
        elif location not in JewelryItem.Location.values:
            row_errors.append(
                f"location must be one of: {', '.join(JewelryItem.Location.values)}"
            )

        karat = None
        try:
            karat = int(row.get("karat", ""))
            if karat not in JewelryItem.Karat.values:
                row_errors.append(
                    f"karat must be one of: {', '.join(str(value) for value in JewelryItem.Karat.values)}"
                )
        except (TypeError, ValueError):
            row_errors.append("karat must be 18, 21, or 24")

        def positive_decimal(column, label):
            raw_value = row.get(column, "")
            try:
                value = Decimal(raw_value)
            except (InvalidOperation, TypeError, ValueError):
                row_errors.append(f"{label} must be a valid number greater than zero")
                return None
            if not value.is_finite() or value <= 0:
                row_errors.append(f"{label} must be greater than zero")
                return None
            return value

        weight = positive_decimal("weight_grams", "weight_grams")
        cost = positive_decimal("cost_price", "cost_price")

        quantity = None
        try:
            quantity = int(row.get("quantity", ""))
            if quantity <= 0:
                row_errors.append("quantity must be at least 1")
        except (TypeError, ValueError):
            row_errors.append("quantity must be a whole number of at least 1")

        if row_errors:
            errors.extend(f"Row {row_number}: {error}." for error in row_errors)
            continue

        values = {
            "barcode": barcode,
            "name": name,
            "category": category,
            "karat": karat,
            "weight_grams": weight,
            "stone_details": row.get("stone_details", ""),
            "location": location,
            "unit_cost": cost,
            "quantity": quantity,
        }
        candidate = PurchaseLine(**values)
        try:
            candidate.full_clean(exclude=("purchase", "created_item"))
        except ValidationError as error:
            errors.extend(f"Row {row_number}: {message}" for message in error.messages)
            continue

        parsed_rows.append({"row_number": row_number, "values": values})

    if not parsed_rows and not errors:
        errors.append("The CSV contains no inventory rows.")

    seen_barcodes = {}
    for parsed in parsed_rows:
        barcode = parsed["values"]["barcode"]
        if not barcode:
            continue
        if barcode in seen_barcodes:
            errors.append(
                f"Row {parsed['row_number']}: barcode {barcode} is already used on "
                f"row {seen_barcodes[barcode]}."
            )
        else:
            seen_barcodes[barcode] = parsed["row_number"]

    existing_barcodes = set(
        JewelryItem.objects.filter(barcode__in=seen_barcodes).values_list("barcode", flat=True)
    )
    for barcode in sorted(existing_barcodes):
        errors.append(
            f"Row {seen_barcodes[barcode]}: barcode {barcode} already exists in inventory."
        )

    return parsed_rows, errors


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
    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            messages.error(request, "Choose a CSV file to import.")
            return redirect("inventory:import_stock")

        parsed_rows, errors = _parse_import_file(uploaded_file)
        if errors:
            messages.error(request, "Import cancelled. No inventory or accounting records were created.")
            for error in errors[:20]:
                messages.error(request, error)
            if len(errors) > 20:
                messages.error(request, f"There are {len(errors) - 20} additional error(s) in the file.")
            return redirect("inventory:import_stock")

        # Every valid import becomes ONE opening-stock purchase. The transaction
        # guarantees that a later row or ledger failure rolls the whole batch back.
        try:
            with transaction.atomic():
                batch = Purchase.objects.create(is_opening=True)
                for parsed in parsed_rows:
                    PurchaseLine.objects.create(
                        purchase=batch,
                        **parsed["values"],
                    )
                batch.post_to_ledger()
        except (ValidationError, IntegrityError) as error:
            messages.error(
                request,
                "Import cancelled. No inventory or accounting records were created. "
                f"{error}",
            )
            return redirect("inventory:import_stock")

        messages.success(
            request,
            f"Imported {len(parsed_rows)} item(s) as Opening stock #{batch.pk}. "
            f"Delete that purchase in Admin → Purchases to undo the whole batch."
        )
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
