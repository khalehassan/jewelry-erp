from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import render, get_object_or_404

from inventory.models import JewelryItem
from .models import Account


def _money(x):
    return f"{x:,.2f}"


def _by_type(t):
    rows = []
    total = Decimal("0.00")
    for acc in Account.objects.filter(type=t):
        bal = acc.balance
        rows.append({"account": acc, "balance": _money(bal)})
        total += bal
    return rows, total


def reports_index(request):
    return render(request, "accounting/reports_index.html")


def trial_balance(request):
    trial = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for acc in Account.objects.all():
        agg = acc.lines.aggregate(d=Sum("debit"), c=Sum("credit"))
        d = agg["d"] or Decimal("0.00")
        c = agg["c"] or Decimal("0.00")
        net = d - c
        debit_col = net if net > 0 else Decimal("0.00")
        credit_col = -net if net < 0 else Decimal("0.00")
        total_debit += debit_col
        total_credit += credit_col
        trial.append({"account": acc, "debit": _money(debit_col), "credit": _money(credit_col)})
    return render(request, "accounting/trial_balance.html", {
        "trial": trial,
        "total_debit": _money(total_debit),
        "total_credit": _money(total_credit),
    })


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