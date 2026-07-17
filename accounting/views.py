from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import render, get_object_or_404

from .models import Account


def _money(x):
    return f"{x:,.2f}"


def reports(request):
    accounts = list(Account.objects.all())

    # --- Trial Balance ---
    trial = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for acc in accounts:
        agg = acc.lines.aggregate(d=Sum("debit"), c=Sum("credit"))
        d = agg["d"] or Decimal("0.00")
        c = agg["c"] or Decimal("0.00")
        net = d - c
        debit_col = net if net > 0 else Decimal("0.00")
        credit_col = -net if net < 0 else Decimal("0.00")
        total_debit += debit_col
        total_credit += credit_col
        trial.append({"account": acc, "debit": _money(debit_col), "credit": _money(credit_col)})

    def by_type(t):
        rows = []
        total = Decimal("0.00")
        for acc in accounts:
            if acc.type == t:
                bal = acc.balance
                rows.append({"account": acc, "balance": _money(bal)})
                total += bal
        return rows, total

    revenue_rows, revenue_total = by_type(Account.Type.REVENUE)
    expense_rows, expense_total = by_type(Account.Type.EXPENSE)
    net_profit = revenue_total - expense_total

    asset_rows, asset_total = by_type(Account.Type.ASSET)
    liability_rows, liability_total = by_type(Account.Type.LIABILITY)
    equity_rows, equity_total = by_type(Account.Type.EQUITY)

    return render(request, "accounting/reports.html", {
        "trial": trial,
        "total_debit": _money(total_debit),
        "total_credit": _money(total_credit),
        "revenue_rows": revenue_rows,
        "revenue_total": _money(revenue_total),
        "expense_rows": expense_rows,
        "expense_total": _money(expense_total),
        "net_profit": _money(net_profit),
        "asset_rows": asset_rows,
        "asset_total": _money(asset_total),
        "liability_rows": liability_rows,
        "equity_rows": equity_rows,
        "total_liab_equity_profit": _money(liability_total + equity_total + net_profit),
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