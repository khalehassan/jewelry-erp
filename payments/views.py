from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
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
        billed = sum((s.total for s in customer.sales.filter(on_credit=True)), Decimal("0.00"))
        paid = sum((p.amount for p in customer.payments.filter(kind=Payment.Kind.RECEIVE)), Decimal("0.00"))
        outstanding = billed - paid
        if billed or paid:
            rows.append({
                "name": customer.name,
                "billed": money(billed),
                "paid": money(paid),
                "outstanding": money(outstanding),
                "settled": outstanding <= 0,
            })
    return rows


def supplier_rows():
    """What we still owe each supplier: credit purchases minus money paid."""
    rows = []
    for supplier in Supplier.objects.all().order_by("name"):
        billed = sum((p.total for p in supplier.purchases.filter(on_credit=True)), Decimal("0.00"))
        paid = sum((p.amount for p in supplier.payments.filter(kind=Payment.Kind.PAY)), Decimal("0.00"))
        outstanding = billed - paid
        if billed or paid:
            rows.append({
                "name": supplier.name,
                "billed": money(billed),
                "paid": money(paid),
                "outstanding": money(outstanding),
                "settled": outstanding <= 0,
            })
    return rows


@require_perm("payments.add_payment")
def payments_page(request):
    if request.method == "POST":
        kind = request.POST.get("kind")

        try:
            amount = Decimal(request.POST.get("amount") or "0")
        except InvalidOperation:
            amount = Decimal("0")

        if amount <= 0:
            messages.error(request, "Enter an amount greater than zero.")
            return redirect("payments:payments")

        if kind == Payment.Kind.RECEIVE:
            customer_id = request.POST.get("customer")
            if not customer_id:
                messages.error(request, "Choose a customer.")
                return redirect("payments:payments")
            payment = Payment.objects.create(
                kind=Payment.Kind.RECEIVE,
                customer_id=customer_id,
                amount=amount,
                note=(request.POST.get("note") or "").strip(),
            )
            payment.post_to_ledger()
            messages.success(request, f"Received {money(amount)} EGP from {payment.customer.name}.")

        elif kind == Payment.Kind.PAY:
            supplier_id = request.POST.get("supplier")
            if not supplier_id:
                messages.error(request, "Choose a supplier.")
                return redirect("payments:payments")
            payment = Payment.objects.create(
                kind=Payment.Kind.PAY,
                supplier_id=supplier_id,
                amount=amount,
                note=(request.POST.get("note") or "").strip(),
            )
            payment.post_to_ledger()
            messages.success(request, f"Paid {money(amount)} EGP to {payment.supplier.name}.")

        else:
            messages.error(request, "Unknown payment type.")

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

    return render(request, "payments/payments.html", {
        "customers": Customer.objects.all().order_by("name"),
        "suppliers": Supplier.objects.all().order_by("name"),
        "customer_rows": customer_rows(),
        "supplier_rows": supplier_rows(),
        "recent": recent,
    })
