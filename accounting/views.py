from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.dateparse import parse_date

from inventory.models import JewelryItem
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