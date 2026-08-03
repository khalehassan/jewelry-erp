from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.dateparse import parse_date

from inventory.models import JewelryItem
from payments.models import Payment
from purchases.models import Purchase, PurchaseLine
from sales.models import Sale, SaleLine
from . import mapping
from .models import Account, JournalLine


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


def _money(x):
    return f"{x:,.2f}"


def _weight(x):
    return f"{x:,.3f}"


def _round_money(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _line_totals(date_from=None, date_to=None, account_ids=None):
    lines = JournalLine.objects.all()
    if date_from is not None:
        lines = lines.filter(entry__date__gte=date_from)
    if date_to is not None:
        lines = lines.filter(entry__date__lte=date_to)
    if account_ids is not None:
        lines = lines.filter(account_id__in=account_ids)
    return {
        row["account_id"]: (
            row["debit"] or Decimal("0.00"),
            row["credit"] or Decimal("0.00"),
        )
        for row in lines.values("account_id").annotate(
            debit=Sum("debit"),
            credit=Sum("credit"),
        )
    }


def _normal_balance(account, debit, credit):
    if account.type in (Account.Type.ASSET, Account.Type.EXPENSE):
        return debit - credit
    return credit - debit


def _account_balance(code, date_to=None):
    account = Account.objects.get(code=code)
    debit, credit = _line_totals(
        date_to=date_to,
        account_ids=[account.pk],
    ).get(account.pk, (Decimal("0.00"), Decimal("0.00")))
    return _normal_balance(account, debit, credit)


def _by_type(account_type, date_from=None, date_to=None):
    """Ledger balances for detail accounts in one explicit reporting period."""
    accounts = list(Account.objects.filter(type=account_type, is_group=False))
    totals = _line_totals(
        date_from=date_from,
        date_to=date_to,
        account_ids=[account.pk for account in accounts],
    )
    rows = []
    total = Decimal("0.00")
    for account in accounts:
        debit, credit = totals.get(account.pk, (Decimal("0.00"), Decimal("0.00")))
        balance = _normal_balance(account, debit, credit)
        if balance:
            rows.append({"account": account, "balance": _money(balance)})
        total += balance
    return rows, total


def _operational_reconciliation(as_of):
    zero = Decimal("0.00")
    inventory_value = sum(
        (
            item.cost_price * item.quantity
            for item in JewelryItem.objects.filter(is_archived=False, quantity__gt=0)
        ),
        zero,
    )
    inventory_ledger = sum(
        (_account_balance(mapping.gold_inventory(karat), as_of) for karat in (18, 21, 24)),
        zero,
    )

    active_credit_sales = Sale.objects.filter(
        on_credit=True,
        journal_entry__date__lte=as_of,
    ).filter(
        Q(reversal_journal_entry__isnull=True)
        | Q(reversal_journal_entry__date__gt=as_of)
    )
    credit_sales = sum(
        (
            _round_money(sale.total)
            for sale in active_credit_sales
        ),
        zero,
    )
    customer_receipts = sum(
        Payment.objects.filter(
            kind=Payment.Kind.RECEIVE,
            journal_entry__date__lte=as_of,
        ).values_list("amount", flat=True),
        zero,
    )
    receivable_operational = credit_sales - customer_receipts
    receivable_ledger = _account_balance(mapping.RETAIL_RECEIVABLE, as_of)

    active_credit_purchases = Purchase.objects.filter(
        on_credit=True,
        journal_entry__date__lte=as_of,
    ).filter(
        Q(reversal_journal_entry__isnull=True)
        | Q(reversal_journal_entry__date__gt=as_of)
    )
    credit_purchases = sum(
        (
            purchase.total
            for purchase in active_credit_purchases
        ),
        zero,
    )
    supplier_payments = sum(
        Payment.objects.filter(
            kind=Payment.Kind.PAY,
            journal_entry__date__lte=as_of,
        ).values_list("amount", flat=True),
        zero,
    )
    payable_operational = credit_purchases - supplier_payments
    payable_ledger = _account_balance(mapping.SUPPLIER_PAYABLE, as_of)

    raw_checks = [
        ("Inventory at cost", inventory_value, inventory_ledger),
        ("Customer receivables", receivable_operational, receivable_ledger),
        ("Supplier payables", payable_operational, payable_ledger),
    ]
    checks = []
    for label, operational, ledger in raw_checks:
        difference = operational - ledger
        checks.append({
            "label": label,
            "operational": _money(operational),
            "ledger": _money(ledger),
            "difference": _money(difference),
            "is_reconciled": difference == 0,
        })

    unposted = {
        "purchases": Purchase.objects.filter(
            journal_entry__isnull=True,
            lines__isnull=False,
        ).distinct().count(),
        "sales": Sale.objects.filter(
            journal_entry__isnull=True,
            lines__isnull=False,
        ).distinct().count(),
        "payments": Payment.objects.filter(journal_entry__isnull=True).count(),
    }
    return {
        "checks": checks,
        "is_reconciled": all(check["is_reconciled"] for check in checks) and not any(unposted.values()),
        "unposted": unposted,
        "unposted_total": sum(unposted.values()),
    }


def _split(net):
    """A net movement becomes a debit column or a credit column, never both."""
    if net > 0:
        return net, Decimal("0.00")
    if net < 0:
        return Decimal("0.00"), -net
    return Decimal("0.00"), Decimal("0.00")


@require_perm("accounting.view_account")
def reports_index(request):
    as_of = timezone.localdate()
    return render(request, "accounting/reports_index.html", {
        "as_of": as_of.isoformat(),
        "reconciliation": _operational_reconciliation(as_of),
    })


@require_perm("accounting.view_account")
def trial_balance(request):
    today = timezone.localdate()
    date_from = parse_date(request.GET.get("from") or "") or today.replace(month=1, day=1)
    date_to = parse_date(request.GET.get("to") or "") or today
    level = request.GET.get("level") or "all"        # all | detail | summary
    show = request.GET.get("show") or "nonzero"      # all | nonzero | movement

    if date_from > date_to:
        date_from, date_to = date_to, date_from
        messages.info(request, "The dates were reversed, so they have been put in chronological order.")

    accounts = list(Account.objects.select_related("parent").order_by("code"))
    by_id = {a.pk: a for a in accounts}

    children = {a.pk: [] for a in accounts}
    for a in accounts:
        if a.parent_id in children:
            children[a.parent_id].append(a.pk)

    zero = Decimal("0.00")
    own = {a.pk: {"od": zero, "oc": zero, "pd": zero, "pc": zero} for a in accounts}

    opening_rows = (
        JournalLine.objects.filter(entry__date__lt=date_from)
        .values("account_id").annotate(d=Sum("debit"), c=Sum("credit"))
    )
    for row in opening_rows:
        if row["account_id"] in own:
            own[row["account_id"]]["od"] = row["d"] or zero
            own[row["account_id"]]["oc"] = row["c"] or zero

    period_rows = (
        JournalLine.objects.filter(entry__date__gte=date_from, entry__date__lte=date_to)
        .values("account_id").annotate(d=Sum("debit"), c=Sum("credit"))
    )
    for row in period_rows:
        if row["account_id"] in own:
            own[row["account_id"]]["pd"] = row["d"] or zero
            own[row["account_id"]]["pc"] = row["c"] or zero

    # A heading shows the total of everything nested beneath it.
    rolled = {}

    def roll_up(pk):
        if pk in rolled:
            return rolled[pk]
        totals = dict(own[pk])
        for child_pk in children[pk]:
            child = roll_up(child_pk)
            for key in totals:
                totals[key] += child[key]
        rolled[pk] = totals
        return totals

    for a in accounts:
        roll_up(a.pk)

    rows = []
    total_debit = total_credit = zero
    for account in accounts:
        t = rolled[account.pk]
        opening_net = t["od"] - t["oc"]
        period_net = t["pd"] - t["pc"]
        closing_net = opening_net + period_net

        open_d, open_c = _split(opening_net)
        close_d, close_c = _split(closing_net)

        # Only detail accounts feed the totals, or headings would count twice.
        if not account.is_group:
            total_debit += close_d
            total_credit += close_c

        if level == "detail" and account.is_group:
            continue
        if level == "summary" and account.parent_id is not None:
            continue
        has_movement = t["pd"] or t["pc"]
        if show == "nonzero" and not (has_movement or opening_net or closing_net):
            continue
        if show == "movement" and not has_movement:
            continue

        ancestors = []
        node = account.parent_id
        while node is not None:
            ancestors.append(by_id[node].code)
            node = by_id[node].parent_id

        rows.append({
            "account": account,
            "depth": len(ancestors),
            "ancestors": " ".join(ancestors),
            "opening_debit": _money(open_d),
            "opening_credit": _money(open_c),
            "period_debit": _money(t["pd"]),
            "period_credit": _money(t["pc"]),
            "closing_debit": _money(close_d),
            "closing_credit": _money(close_c),
        })

    return render(request, "accounting/trial_balance.html", {
        "rows": rows,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "level": level,
        "show": show,
        "total_debit": _money(total_debit),
        "total_credit": _money(total_credit),
        "difference": _money(abs(total_debit - total_credit)),
        "is_balanced": total_debit == total_credit,
        "row_count": len(rows),
    })


@require_perm("accounting.view_account")
def income_statement(request):
    today = timezone.localdate()
    date_from = parse_date(request.GET.get("from") or "") or today.replace(month=1, day=1)
    date_to = parse_date(request.GET.get("to") or "") or today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
        messages.info(request, "The dates were reversed, so they have been put in chronological order.")

    revenue_rows, revenue_total = _by_type(
        Account.Type.REVENUE,
        date_from=date_from,
        date_to=date_to,
    )
    expense_rows, expense_total = _by_type(
        Account.Type.EXPENSE,
        date_from=date_from,
        date_to=date_to,
    )
    net_profit = revenue_total - expense_total
    return render(request, "accounting/income_statement.html", {
        "revenue_rows": revenue_rows,
        "revenue_total": _money(revenue_total),
        "expense_rows": expense_rows,
        "expense_total": _money(expense_total),
        "net_profit": _money(net_profit),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    })


@require_perm("accounting.view_account")
def balance_sheet(request):
    as_of = parse_date(request.GET.get("to") or "") or timezone.localdate()
    asset_rows, asset_total = _by_type(Account.Type.ASSET, date_to=as_of)
    liability_rows, liability_total = _by_type(Account.Type.LIABILITY, date_to=as_of)
    equity_rows, equity_total = _by_type(Account.Type.EQUITY, date_to=as_of)
    _, revenue_total = _by_type(Account.Type.REVENUE, date_to=as_of)
    _, expense_total = _by_type(Account.Type.EXPENSE, date_to=as_of)
    net_profit = revenue_total - expense_total
    total_liabilities_equity = liability_total + equity_total + net_profit
    difference = asset_total - total_liabilities_equity
    return render(request, "accounting/balance_sheet.html", {
        "asset_rows": asset_rows,
        "asset_total": _money(asset_total),
        "liability_rows": liability_rows,
        "equity_rows": equity_rows,
        "net_profit": _money(net_profit),
        "total_liab_equity_profit": _money(total_liabilities_equity),
        "difference": _money(abs(difference)),
        "is_balanced": difference == 0,
        "as_of": as_of.isoformat(),
    })


@require_perm("accounting.view_account")
def inventory_report(request):
    as_of = timezone.localdate()
    items = JewelryItem.objects.filter(
        is_archived=False,
        quantity__gt=0,
    ).order_by("location", "name")
    total_cost = Decimal("0.00")
    physical_by_karat = {karat: Decimal("0.00") for karat in (18, 21, 24)}
    piece_count = 0
    rows = []
    for item in items:
        line_cost = item.cost_price * item.quantity
        total_cost += line_cost
        if item.karat in physical_by_karat:
            physical_by_karat[item.karat] += line_cost
        piece_count += item.quantity
        rows.append({"item": item, "line_cost": _money(line_cost)})

    summaries = []
    total_ledger = Decimal("0.00")
    for karat in (18, 21, 24):
        ledger = _account_balance(mapping.gold_inventory(karat), as_of)
        physical = physical_by_karat[karat]
        difference = physical - ledger
        total_ledger += ledger
        summaries.append({
            "karat": karat,
            "physical": _money(physical),
            "ledger": _money(ledger),
            "difference": _money(difference),
            "is_reconciled": difference == 0,
        })
    total_difference = total_cost - total_ledger
    return render(request, "accounting/inventory_report.html", {
        "rows": rows,
        "total_cost": _money(total_cost),
        "ledger_total": _money(total_ledger),
        "difference": _money(total_difference),
        "is_reconciled": total_difference == 0,
        "summaries": summaries,
        "item_count": piece_count,
        "sku_count": len(rows),
        "as_of": as_of.isoformat(),
    })


@require_perm("accounting.view_account")
def bank_movement(request):
    """Movement and statement reconciliation for one bank/detail payment account."""
    today = timezone.localdate()
    date_from = parse_date(request.GET.get("from") or "") or today.replace(day=1)
    date_to = parse_date(request.GET.get("to") or "") or today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
        messages.info(
            request,
            "The dates were reversed, so they have been put in chronological order.",
        )

    bank_accounts = list(
        Account.objects.filter(
            parent__code="1020",
            is_group=False,
        ).order_by("code")
    )
    selected_code = (request.GET.get("account") or mapping.BANK).strip()
    account = next(
        (candidate for candidate in bank_accounts if candidate.code == selected_code),
        None,
    )
    if account is None:
        account = next(
            (candidate for candidate in bank_accounts if candidate.code == mapping.BANK),
            bank_accounts[0],
        )
        messages.info(request, "The selected bank account was not valid, so the default was used.")

    opening_totals = account.lines.filter(entry__date__lt=date_from).aggregate(
        debit=Sum("debit"),
        credit=Sum("credit"),
    )
    opening_balance = (
        (opening_totals["debit"] or Decimal("0.00"))
        - (opening_totals["credit"] or Decimal("0.00"))
    )
    running_balance = opening_balance
    money_in_total = Decimal("0.00")
    money_out_total = Decimal("0.00")
    rows = []
    lines = account.lines.filter(
        entry__date__range=(date_from, date_to),
    ).select_related("entry").order_by("entry__date", "entry__id", "id")
    for line in lines:
        money_in_total += line.debit
        money_out_total += line.credit
        running_balance += line.debit - line.credit
        rows.append({
            "entry_id": line.entry_id,
            "date": line.entry.date,
            "description": line.entry.description or f"Journal entry #{line.entry_id}",
            "money_in": _money(line.debit) if line.debit else "—",
            "money_out": _money(line.credit) if line.credit else "—",
            "running_balance": _money(running_balance),
            "running_class": "negative" if running_balance < 0 else "positive",
        })

    actual_raw = (request.GET.get("actual_balance") or "").strip()
    actual_input = actual_raw
    actual_balance = None
    actual_error = ""
    if actual_raw:
        try:
            actual_balance = Decimal(actual_raw.replace(",", ""))
            if not actual_balance.is_finite():
                raise InvalidOperation
            actual_balance = _round_money(actual_balance)
            actual_input = f"{actual_balance:.2f}"
        except (InvalidOperation, TypeError, ValueError):
            actual_error = "Enter a valid actual bank ending balance."
            actual_balance = None

    difference = None
    is_matched = False
    if actual_balance is not None:
        difference = actual_balance - running_balance
        is_matched = difference == 0

    return render(request, "accounting/bank_movement.html", {
        "account": account,
        "bank_accounts": bank_accounts,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "actual_input": actual_input,
        "actual_error": actual_error,
        "actual_balance": _money(actual_balance) if actual_balance is not None else "",
        "difference": _money(difference) if difference is not None else "",
        "is_matched": is_matched,
        "has_actual_balance": actual_balance is not None,
        "opening_balance": _money(opening_balance),
        "money_in_total": _money(money_in_total),
        "money_out_total": _money(money_out_total),
        "ending_balance": _money(running_balance),
        "ending_class": "negative" if running_balance < 0 else "positive",
        "rows": rows,
    })


@require_perm("accounting.view_account")
def gold_movement(request):
    """Chronological gold ledger with a running physical-weight balance."""
    today = timezone.localdate()
    date_from = parse_date(request.GET.get("from") or "") or today.replace(day=1)
    date_to = parse_date(request.GET.get("to") or "") or today

    if date_from > date_to:
        date_from, date_to = date_to, date_from
        messages.info(request, "The dates were reversed, so they have been put in chronological order.")

    zero = Decimal("0.000")
    karats = [18, 21, 24]

    purchase_weight = ExpressionWrapper(
        F("weight_grams") * F("quantity"),
        output_field=DecimalField(max_digits=18, decimal_places=3),
    )

    # The ledger must carry its balance into the selected period. Opening-stock
    # imports are included here because they establish the physical gold held.
    opening_balances = {karat: zero for karat in karats}
    opening_purchase_rows = (
        PurchaseLine.objects
        .filter(purchase__journal_entry__date__lt=date_from)
        .values("karat")
        .annotate(weight=Sum(purchase_weight))
        .order_by()
    )
    for result in opening_purchase_rows:
        if result["karat"] in karats:
            opening_balances[result["karat"]] += result["weight"] or zero

    opening_reversal_rows = (
        PurchaseLine.objects
        .filter(purchase__reversal_journal_entry__date__lt=date_from)
        .values("karat")
        .annotate(weight=Sum(purchase_weight))
        .order_by()
    )
    for result in opening_reversal_rows:
        if result["karat"] in karats:
            opening_balances[result["karat"]] -= result["weight"] or zero

    sale_weight = ExpressionWrapper(
        F("item__weight_grams") * F("quantity"),
        output_field=DecimalField(max_digits=18, decimal_places=3),
    )
    opening_sale_rows = (
        SaleLine.objects
        .filter(sale__journal_entry__date__lt=date_from)
        .values("item__karat")
        .annotate(weight=Sum(sale_weight))
        .order_by()
    )
    for result in opening_sale_rows:
        karat = result["item__karat"]
        if karat in karats:
            opening_balances[karat] -= result["weight"] or zero

    opening_sale_reversal_rows = (
        SaleLine.objects
        .filter(sale__reversal_journal_entry__date__lt=date_from)
        .values("item__karat")
        .annotate(weight=Sum(sale_weight))
        .order_by()
    )
    for result in opening_sale_reversal_rows:
        karat = result["item__karat"]
        if karat in karats:
            opening_balances[karat] += result["weight"] or zero

    # One row per business transaction and karat. Multiple jewelry items of the
    # same karat on one purchase or sale are deliberately combined.
    events = []
    period_purchase_rows = (
        PurchaseLine.objects
        .filter(purchase__journal_entry__date__range=(date_from, date_to))
        .values(
            "purchase_id",
            "purchase__created_at",
            "purchase__journal_entry__date",
            "purchase__is_opening",
            "purchase__on_credit",
            "purchase__payment_method",
            "purchase__supplier__name",
            "karat",
        )
        .annotate(weight=Sum(purchase_weight))
        .order_by()
    )
    for result in period_purchase_rows:
        is_opening = result["purchase__is_opening"]
        supplier = result["purchase__supplier__name"] or ""
        if result["purchase__on_credit"]:
            payment_method = "On credit"
        else:
            payment_method = dict(Purchase.PaymentMethod.choices).get(
                result["purchase__payment_method"],
                "Other",
            )
        details = " · ".join(
            value for value in (supplier, payment_method) if value
        )
        events.append({
            "occurred_at": result["purchase__created_at"],
            "ledger_date": result["purchase__journal_entry__date"],
            "sort_order": 0,
            "source_id": result["purchase_id"],
            "kind": "Opening stock" if is_opening else "Purchase",
            "kind_class": "opening" if is_opening else "purchase",
            "reference": (
                f"Opening stock #{result['purchase_id']}"
                if is_opening else f"Purchase #{result['purchase_id']}"
            ),
            "party": "" if is_opening else details,
            "karat": result["karat"],
            "received_raw": result["weight"] or zero,
            "out_raw": zero,
        })

    period_sale_rows = (
        SaleLine.objects
        .filter(sale__journal_entry__date__range=(date_from, date_to))
        .values(
            "sale_id",
            "sale__created_at",
            "sale__journal_entry__date",
            "sale__customer__name",
            "sale__on_credit",
            "sale__payment_method",
            "item__karat",
        )
        .annotate(weight=Sum(sale_weight))
        .order_by()
    )
    for result in period_sale_rows:
        customer = result["sale__customer__name"] or "Walk-in customer"
        if result["sale__on_credit"]:
            payment_method = "On credit"
        else:
            payment_method = dict(Sale.PaymentMethod.choices).get(
                result["sale__payment_method"],
                "Other",
            )
        events.append({
            "occurred_at": result["sale__created_at"],
            "ledger_date": result["sale__journal_entry__date"],
            "sort_order": 1,
            "source_id": result["sale_id"],
            "kind": "Sale",
            "kind_class": "sale",
            "reference": f"Sale #{result['sale_id']}",
            "party": f"{customer} · {payment_method}",
            "karat": result["item__karat"],
            "received_raw": zero,
            "out_raw": result["weight"] or zero,
        })

    period_reversal_rows = (
        PurchaseLine.objects
        .filter(purchase__reversal_journal_entry__date__range=(date_from, date_to))
        .values(
            "purchase_id",
            "purchase__reversed_at",
            "purchase__reversal_journal_entry__date",
            "purchase__supplier__name",
            "purchase__reversal_reason",
            "karat",
        )
        .annotate(weight=Sum(purchase_weight))
        .order_by()
    )
    for result in period_reversal_rows:
        supplier = result["purchase__supplier__name"] or ""
        reason = result["purchase__reversal_reason"]
        details = " · ".join(value for value in (supplier, reason) if value)
        events.append({
            "occurred_at": result["purchase__reversed_at"],
            "ledger_date": result["purchase__reversal_journal_entry__date"],
            "sort_order": 2,
            "source_id": result["purchase_id"],
            "kind": "Purchase reversal",
            "kind_class": "reversal",
            "reference": f"Reversal of Purchase #{result['purchase_id']}",
            "party": details,
            "karat": result["karat"],
            "received_raw": zero,
            "out_raw": result["weight"] or zero,
        })

    period_sale_reversal_rows = (
        SaleLine.objects
        .filter(sale__reversal_journal_entry__date__range=(date_from, date_to))
        .values(
            "sale_id",
            "sale__reversed_at",
            "sale__reversal_journal_entry__date",
            "sale__customer__name",
            "sale__reversal_reason",
            "item__karat",
        )
        .annotate(weight=Sum(sale_weight))
        .order_by()
    )
    for result in period_sale_reversal_rows:
        customer = result["sale__customer__name"] or "Walk-in customer"
        reason = result["sale__reversal_reason"]
        details = " · ".join(value for value in (customer, reason) if value)
        events.append({
            "occurred_at": result["sale__reversed_at"],
            "ledger_date": result["sale__reversal_journal_entry__date"],
            "sort_order": 3,
            "source_id": result["sale_id"],
            "kind": "Sale reversal",
            "kind_class": "sale-reversal",
            "reference": f"Reversal of Sale #{result['sale_id']}",
            "party": details,
            "karat": result["item__karat"],
            "received_raw": result["weight"] or zero,
            "out_raw": zero,
        })

    events.sort(key=lambda event: (
        event["ledger_date"],
        event["occurred_at"],
        event["sort_order"],
        event["source_id"],
        event["karat"],
    ))

    running_balances = dict(opening_balances)
    period_totals = {
        karat: {"received": zero, "out": zero} for karat in karats
    }
    rows = []
    for event in events:
        karat = event["karat"]
        if karat not in karats:
            continue
        received = event["received_raw"]
        weight_out = event["out_raw"]
        running_balances[karat] += received - weight_out
        period_totals[karat]["received"] += received
        period_totals[karat]["out"] += weight_out
        rows.append({
            **event,
            "received": _weight(received) if received else "—",
            "out": _weight(weight_out) if weight_out else "—",
            "balance": _weight(running_balances[karat]),
            "balance_class": "negative" if running_balances[karat] < 0 else "positive",
        })

    show_physical_reconciliation = date_to == timezone.localdate()
    physical_weights = {karat: zero for karat in karats}
    if show_physical_reconciliation:
        for item in JewelryItem.objects.filter(is_archived=False, quantity__gt=0):
            if item.karat in physical_weights:
                physical_weights[item.karat] += item.weight_grams * item.quantity

    summaries = []
    for karat in karats:
        closing = running_balances[karat]
        physical = physical_weights[karat]
        difference = physical - closing
        summaries.append({
            "karat": karat,
            "opening": _weight(opening_balances[karat]),
            "received": _weight(period_totals[karat]["received"]),
            "out": _weight(period_totals[karat]["out"]),
            "closing": _weight(closing),
            "closing_class": "negative" if closing < 0 else "positive",
            "physical": _weight(physical),
            "difference": _weight(difference),
            "is_reconciled": difference == 0,
        })

    unposted_purchases = Purchase.objects.filter(
        journal_entry__isnull=True,
        lines__isnull=False,
    ).distinct().count()
    unposted_sales = Sale.objects.filter(
        journal_entry__isnull=True,
        lines__isnull=False,
    ).distinct().count()

    return render(request, "accounting/gold_movement.html", {
        "rows": rows,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "summaries": summaries,
        "show_physical_reconciliation": show_physical_reconciliation,
        "is_reconciled": (
            show_physical_reconciliation
            and all(summary["is_reconciled"] for summary in summaries)
            and not unposted_purchases
            and not unposted_sales
        ),
        "unposted_purchases": unposted_purchases,
        "unposted_sales": unposted_sales,
    })


@require_perm("accounting.view_account")
def account_detail(request, code):
    account = get_object_or_404(Account, code=code)
    today = timezone.localdate()
    date_from = parse_date(request.GET.get("from") or "") or today.replace(month=1, day=1)
    date_to = parse_date(request.GET.get("to") or "") or today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
        messages.info(request, "The dates were reversed, so they have been put in chronological order.")

    opening_totals = account.lines.filter(entry__date__lt=date_from).aggregate(
        debit=Sum("debit"),
        credit=Sum("credit"),
    )
    opening_debit = opening_totals["debit"] or Decimal("0.00")
    opening_credit = opening_totals["credit"] or Decimal("0.00")
    lines = account.lines.filter(
        entry__date__range=(date_from, date_to),
    ).select_related("entry").order_by("entry__date", "entry__id", "id")
    is_debit_normal = account.type in (Account.Type.ASSET, Account.Type.EXPENSE)
    running = _normal_balance(account, opening_debit, opening_credit)
    opening_balance = running
    period_debit = Decimal("0.00")
    period_credit = Decimal("0.00")
    rows = []
    for line in lines:
        period_debit += line.debit
        period_credit += line.credit
        if is_debit_normal:
            running += line.debit - line.credit
        else:
            running += line.credit - line.debit
        rows.append({
            "line": line,
            "debit": _money(line.debit),
            "credit": _money(line.credit),
            "running": _money(running),
        })
    return render(request, "accounting/account_detail.html", {
        "account": account,
        "account_balance": _money(running),
        "opening_balance": _money(opening_balance),
        "period_debit": _money(period_debit),
        "period_credit": _money(period_credit),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "rows": rows,
    })
