from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.dateparse import parse_date

from inventory.models import JewelryItem
from purchases.models import PurchaseLine
from sales.models import SaleLine
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


def _by_type(t):
    """Detail accounts only — group headings would double-count their children."""
    rows = []
    total = Decimal("0.00")
    for acc in Account.objects.filter(type=t, is_group=False):
        bal = acc.balance
        if bal:
            rows.append({"account": acc, "balance": _money(bal)})
        total += bal
    return rows, total


def _split(net):
    """A net movement becomes a debit column or a credit column, never both."""
    if net > 0:
        return net, Decimal("0.00")
    if net < 0:
        return Decimal("0.00"), -net
    return Decimal("0.00"), Decimal("0.00")


@require_perm("accounting.view_account")
def reports_index(request):
    return render(request, "accounting/reports_index.html")


@require_perm("accounting.view_account")
def trial_balance(request):
    today = timezone.localdate()
    date_from = parse_date(request.GET.get("from") or "") or today.replace(month=1, day=1)
    date_to = parse_date(request.GET.get("to") or "") or today
    level = request.GET.get("level") or "all"        # all | detail | summary
    show = request.GET.get("show") or "nonzero"      # all | nonzero | movement

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
    revenue_rows, revenue_total = _by_type(Account.Type.REVENUE)
    expense_rows, expense_total = _by_type(Account.Type.EXPENSE)
    net_profit = revenue_total - expense_total
    return render(request, "accounting/income_statement.html", {
        "revenue_rows": revenue_rows,
        "revenue_total": _money(revenue_total),
        "expense_rows": expense_rows,
        "expense_total": _money(expense_total),
        "net_profit": _money(net_profit),
    })


@require_perm("accounting.view_account")
def balance_sheet(request):
    asset_rows, asset_total = _by_type(Account.Type.ASSET)
    liability_rows, liability_total = _by_type(Account.Type.LIABILITY)
    equity_rows, equity_total = _by_type(Account.Type.EQUITY)
    _, revenue_total = _by_type(Account.Type.REVENUE)
    _, expense_total = _by_type(Account.Type.EXPENSE)
    net_profit = revenue_total - expense_total
    return render(request, "accounting/balance_sheet.html", {
        "asset_rows": asset_rows,
        "asset_total": _money(asset_total),
        "liability_rows": liability_rows,
        "equity_rows": equity_rows,
        "net_profit": _money(net_profit),
        "total_liab_equity_profit": _money(liability_total + equity_total + net_profit),
    })


@require_perm("accounting.view_account")
def inventory_report(request):
    items = JewelryItem.objects.all().order_by("location", "name")
    total_cost = Decimal("0.00")
    rows = []
    for item in items:
        line_cost = item.cost_price * item.quantity
        total_cost += line_cost
        rows.append({"item": item, "line_cost": _money(line_cost)})
    return render(request, "accounting/inventory_report.html", {
        "rows": rows,
        "total_cost": _money(total_cost),
        "item_count": items.count(),
    })


@require_perm("accounting.view_account")
def gold_movement(request):
    """Daily gold received and sold, separated by karat and as fine gold."""
    today = timezone.localdate()
    date_from = parse_date(request.GET.get("from") or "") or today.replace(day=1)
    date_to = parse_date(request.GET.get("to") or "") or today

    if date_from > date_to:
        date_from, date_to = date_to, date_from
        messages.info(request, "The dates were reversed, so they have been put in chronological order.")

    zero = Decimal("0.000")
    karats = [18, 21, 24]
    daily = defaultdict(lambda: {
        karat: {"received": zero, "out": zero} for karat in karats
    })

    purchase_weight = ExpressionWrapper(
        F("weight_grams") * F("quantity"),
        output_field=DecimalField(max_digits=18, decimal_places=3),
    )
    purchase_rows = (
        PurchaseLine.objects
        .filter(
            purchase__is_opening=False,
            purchase__created_at__date__range=(date_from, date_to),
        )
        .annotate(day=TruncDate("purchase__created_at"))
        .values("day", "karat")
        .annotate(weight=Sum(purchase_weight))
        .order_by()
    )
    for result in purchase_rows:
        if result["karat"] in karats:
            daily[result["day"]][result["karat"]]["received"] = result["weight"] or zero

    sale_weight = ExpressionWrapper(
        F("item__weight_grams") * F("quantity"),
        output_field=DecimalField(max_digits=18, decimal_places=3),
    )
    sale_rows = (
        SaleLine.objects
        .filter(sale__created_at__date__range=(date_from, date_to))
        .annotate(day=TruncDate("sale__created_at"))
        .values("day", "item__karat")
        .annotate(weight=Sum(sale_weight))
        .order_by()
    )
    for result in sale_rows:
        karat = result["item__karat"]
        if karat in karats:
            daily[result["day"]][karat]["out"] = result["weight"] or zero

    raw_totals = {
        karat: {"received": zero, "out": zero} for karat in karats
    }
    rows = []
    day = date_from
    while day <= date_to:
        movements = []
        fine_received = zero
        fine_out = zero

        for karat in karats:
            received = daily[day][karat]["received"]
            weight_out = daily[day][karat]["out"]
            net = received - weight_out
            fine_received += received * Decimal(karat) / Decimal("24")
            fine_out += weight_out * Decimal(karat) / Decimal("24")
            raw_totals[karat]["received"] += received
            raw_totals[karat]["out"] += weight_out
            movements.append({
                "received": _weight(received),
                "out": _weight(weight_out),
                "net": _weight(net),
                "net_class": "positive" if net > 0 else "negative" if net < 0 else "zero",
            })

        fine_net = fine_received - fine_out
        rows.append({
            "date": day,
            "movements": movements,
            "fine_received": _weight(fine_received),
            "fine_out": _weight(fine_out),
            "fine_net": _weight(fine_net),
            "fine_net_class": "positive" if fine_net > 0 else "negative" if fine_net < 0 else "zero",
        })
        day += timedelta(days=1)

    totals = []
    total_fine_received = zero
    total_fine_out = zero
    for karat in karats:
        received = raw_totals[karat]["received"]
        weight_out = raw_totals[karat]["out"]
        net = received - weight_out
        total_fine_received += received * Decimal(karat) / Decimal("24")
        total_fine_out += weight_out * Decimal(karat) / Decimal("24")
        totals.append({
            "received": _weight(received),
            "out": _weight(weight_out),
            "net": _weight(net),
            "net_class": "positive" if net > 0 else "negative" if net < 0 else "zero",
        })

    total_fine_net = total_fine_received - total_fine_out
    return render(request, "accounting/gold_movement.html", {
        "rows": rows,
        "karats": karats,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "totals": totals,
        "total_fine_received": _weight(total_fine_received),
        "total_fine_out": _weight(total_fine_out),
        "total_fine_net": _weight(total_fine_net),
        "total_fine_net_class": "positive" if total_fine_net > 0 else "negative" if total_fine_net < 0 else "zero",
    })


@require_perm("accounting.view_account")
def account_detail(request, code):
    account = get_object_or_404(Account, code=code)
    lines = account.lines.select_related("entry").order_by("entry__date", "entry__id", "id")
    is_debit_normal = account.type in (Account.Type.ASSET, Account.Type.EXPENSE)
    running = Decimal("0.00")
    rows = []
    for line in lines:
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
        "account_balance": _money(account.balance),
        "rows": rows,
    })
