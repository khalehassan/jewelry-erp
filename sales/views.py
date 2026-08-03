from collections import Counter
from decimal import Decimal, InvalidOperation
from itertools import zip_longest

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from inventory.models import JewelryItem
from customers.models import Customer
from .models import Sale, SaleLine


@login_required
def new_sale(request):
    if request.method == "POST":
        payment_method = (request.POST.get("payment_method") or "").strip()
        item_ids = request.POST.getlist("item")
        golds = request.POST.getlist("gold")
        makings = request.POST.getlist("making")
        qtys = request.POST.getlist("qty")

        errors = []
        if payment_method not in Sale.PaymentMethod.values:
            errors.append("Choose a valid payment method: Cash, Bank, or Other.")
        try:
            discount = Decimal(request.POST.get("discount", ""))
            if not discount.is_finite() or discount < 0:
                errors.append("Discount cannot be negative.")
        except (InvalidOperation, TypeError, ValueError):
            discount = Decimal("0.00")
            errors.append("Enter a valid discount amount.")

        lines = []
        for row_number, values in enumerate(zip_longest(
            item_ids, golds, makings, qtys, fillvalue=""
        ), start=1):
            item_id, gold, making, qty = (str(value).strip() for value in values)
            if not any((item_id, gold, making, qty)):
                continue

            row_errors = []
            try:
                parsed_item_id = int(item_id)
                parsed_gold = Decimal(gold)
                parsed_making = Decimal(making or "0")
                parsed_quantity = int(qty)
            except (InvalidOperation, TypeError, ValueError):
                errors.append(
                    f"Item {row_number}: Select an item and enter valid prices and quantity."
                )
                continue

            if not parsed_gold.is_finite() or parsed_gold <= 0:
                row_errors.append("Gold price per gram must be greater than zero.")
            if not parsed_making.is_finite() or parsed_making < 0:
                row_errors.append("Making charge cannot be negative.")
            if parsed_quantity <= 0:
                row_errors.append("Quantity must be at least 1.")

            if row_errors:
                errors.extend(f"Item {row_number}: {error}" for error in row_errors)
                continue
            lines.append({
                "item_id": parsed_item_id,
                "gold_price_per_gram": parsed_gold,
                "making_charge_per_gram": parsed_making,
                "quantity": parsed_quantity,
            })

        if not lines:
            errors.append("A sale must contain at least one item.")
        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect("sales:new_sale")

        try:
            with transaction.atomic():
                requested_ids = [line["item_id"] for line in lines]
                items = {
                    item.pk: item
                    for item in JewelryItem.objects.select_for_update().filter(
                        pk__in=requested_ids,
                        is_archived=False,
                    )
                }
                missing_ids = set(requested_ids) - set(items)
                if missing_ids:
                    raise ValidationError("One of the selected inventory items no longer exists.")

                duplicate_ids = [
                    item_id
                    for item_id, count in Counter(requested_ids).items()
                    if count > 1
                ]
                if duplicate_ids:
                    duplicate_names = ", ".join(items[item_id].name for item_id in duplicate_ids)
                    raise ValidationError(
                        f"Each inventory item can appear only once. Combine the quantity for: {duplicate_names}."
                    )

                subtotal = Decimal("0.00")
                for line in lines:
                    item = items[line["item_id"]]
                    if line["quantity"] > item.quantity:
                        raise ValidationError(
                            f"Not enough stock for {item.name}: only {item.quantity} available."
                        )
                    subtotal += (
                        item.weight_grams
                        * (line["gold_price_per_gram"] + line["making_charge_per_gram"])
                        * line["quantity"]
                    )

                if subtotal - discount <= 0:
                    raise ValidationError("Sale total must be greater than zero. Reduce the discount.")

                sale = Sale.objects.create(
                    customer_id=request.POST.get("customer") or None,
                    discount=discount,
                    on_credit=bool(request.POST.get("on_credit")),
                    payment_method=payment_method,
                )
                for line in lines:
                    item = items[line["item_id"]]
                    SaleLine.objects.create(
                        sale=sale,
                        item=item,
                        gold_price_per_gram=line["gold_price_per_gram"],
                        making_charge_per_gram=line["making_charge_per_gram"],
                        quantity=line["quantity"],
                    )
                sale.post_to_ledger()
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("sales:new_sale")
        except IntegrityError:
            messages.error(request, "The sale could not be saved because one of its values is invalid.")
            return redirect("sales:new_sale")

        messages.success(request, f"Sale #{sale.pk} saved — total {sale.total:,.2f} EGP")
        return redirect("sales:receipt", pk=sale.pk)

    items = JewelryItem.objects.filter(is_archived=False, quantity__gt=0)
    customers = Customer.objects.all()
    return render(request, "sales/new_sale.html", {
        "items": items,
        "customers": customers,
        "payment_methods": Sale.PaymentMethod.choices,
    })


@login_required
def receipt(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    lines = []
    for line in sale.lines.select_related("item").all():
        lines.append({
            "line": line,
            "gold": f"{line.gold_price_per_gram:,.2f}",
            "making": f"{line.making_charge_per_gram:,.2f}",
            "line_total": f"{line.line_total:,.2f}",
        })
    return render(request, "sales/receipt.html", {
        "sale": sale,
        "lines": lines,
        "subtotal": f"{sale.subtotal:,.2f}",
        "discount": f"{sale.discount:,.2f}",
        "total": f"{sale.total:,.2f}",
    })


@login_required
def dashboard(request):
    today = timezone.localdate()
    todays_sales = Sale.objects.filter(
        created_at__date=today,
        status=Sale.Status.POSTED,
    )
    todays_count = todays_sales.count()
    todays_revenue = sum((s.total for s in todays_sales), Decimal("0.00"))

    todays_cost = Decimal("0.00")
    for s in todays_sales:
        for line in s.lines.all():
            todays_cost += line.item.cost_price * line.quantity
    todays_profit = todays_revenue - todays_cost

    stock_value = Decimal("0.00")
    for item in JewelryItem.objects.filter(is_archived=False):
        stock_value += item.cost_price * item.quantity

    sold = {}
    for line in SaleLine.objects.filter(sale__status=Sale.Status.POSTED):
        sold[line.item.name] = sold.get(line.item.name, 0) + line.quantity
    best_sellers = sorted(sold.items(), key=lambda pair: pair[1], reverse=True)[:5]

    customer_spend = []
    for c in Customer.objects.all():
        spent = sum(
            (s.total for s in c.sales.filter(status=Sale.Status.POSTED)),
            Decimal("0.00"),
        )
        if spent > 0:
            customer_spend.append((c.name, spent))
    customer_spend.sort(key=lambda pair: pair[1], reverse=True)
    top_customers = [{"name": name, "spent": f"{spent:,.2f}"} for name, spent in customer_spend[:5]]

    return render(request, "sales/dashboard.html", {
        "today": today,
        "todays_count": todays_count,
        "todays_revenue": f"{todays_revenue:,.2f}",
        "todays_profit": f"{todays_profit:,.2f}",
        "stock_value": f"{stock_value:,.2f}",
        "best_sellers": best_sellers,
        "top_customers": top_customers,
    })
