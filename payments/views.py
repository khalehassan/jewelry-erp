from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import render, redirect

from customers.models import Customer
from purchases.models import Supplier

from .models import Payment


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


def money(value):
    return f"{value:,.2f}"


def customer_rows():
    """What each customer still owes us: credit sales minus money received."""
    rows = []
    for customer in Customer.objects.all().order_by("name"):
        billed, paid, outstanding = Payment.customer_balance(customer)
        if billed or paid:
            rows.append({
                "party": customer,
                "name": customer.name,
                "billed": money(billed),
                "paid": money(paid),
                "outstanding": money(outstanding),
                "outstanding_amount": outstanding,
                "settled": outstanding <= 0,
            })
    return rows


def supplier_rows():
    """What we still owe each supplier: credit purchases minus money paid."""
    rows = []
    for supplier in Supplier.objects.all().order_by("name"):
        billed, paid, outstanding = Payment.supplier_balance(supplier)
        if billed or paid:
            rows.append({
                "party": supplier,
                "name": supplier.name,
                "billed": money(billed),
                "paid": money(paid),
                "outstanding": money(outstanding),
                "outstanding_amount": outstanding,
                "settled": outstanding <= 0,
            })
    return rows


@require_perm("payments.add_payment")
def payments_page(request):
    if request.method == "POST":
        kind = request.POST.get("kind")

        try:
            amount = Decimal(request.POST.get("amount", ""))
        except (InvalidOperation, TypeError, ValueError):
            amount = Decimal("0")

        if not amount.is_finite() or amount <= 0:
            messages.error(request, "Enter an amount greater than zero.")
            return redirect("payments:payments")

        if kind not in (Payment.Kind.RECEIVE, Payment.Kind.PAY):
            messages.error(request, "Unknown payment type.")
            return redirect("payments:payments")

        try:
            with transaction.atomic():
                if kind == Payment.Kind.RECEIVE:
                    customer_id = request.POST.get("customer")
                    try:
                        customer = Customer.objects.select_for_update().get(pk=customer_id)
                    except (Customer.DoesNotExist, TypeError, ValueError):
                        raise ValidationError("Choose a valid customer.")
                    payment = Payment.objects.create(
                        kind=Payment.Kind.RECEIVE,
                        customer=customer,
                        amount=amount,
                        note=(request.POST.get("note") or "").strip(),
                    )
                else:
                    supplier_id = request.POST.get("supplier")
                    try:
                        supplier = Supplier.objects.select_for_update().get(pk=supplier_id)
                    except (Supplier.DoesNotExist, TypeError, ValueError):
                        raise ValidationError("Choose a valid supplier.")
                    payment = Payment.objects.create(
                        kind=Payment.Kind.PAY,
                        supplier=supplier,
                        amount=amount,
                        note=(request.POST.get("note") or "").strip(),
                    )
                payment.post_to_ledger()
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("payments:payments")
        except IntegrityError:
            messages.error(request, "The payment could not be saved because one of its values is invalid.")
            return redirect("payments:payments")

        if kind == Payment.Kind.RECEIVE:
            messages.success(request, f"Received {money(amount)} EGP from {payment.customer.name}.")
        else:
            messages.success(request, f"Paid {money(amount)} EGP to {payment.supplier.name}.")

        return redirect("payments:payments")

    recent = []
    for p in Payment.objects.select_related("customer", "supplier")[:15]:
        recent.append({
            "id": p.pk,
            "date": p.created_at,
            "label": "Received from" if p.kind == Payment.Kind.RECEIVE else "Paid to",
            "who": p.customer.name if p.customer else (p.supplier.name if p.supplier else "—"),
            "amount": money(p.amount),
            "note": p.note,
        })

    customer_accounts = customer_rows()
    supplier_accounts = supplier_rows()
    return render(request, "payments/payments.html", {
        "customers": [row for row in customer_accounts if row["outstanding_amount"] > 0],
        "suppliers": [row for row in supplier_accounts if row["outstanding_amount"] > 0],
        "customer_rows": customer_accounts,
        "supplier_rows": supplier_accounts,
        "recent": recent,
    })
