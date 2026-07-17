from django.urls import path
from . import views

app_name = "accounting"

urlpatterns = [
    path("reports/", views.reports_index, name="reports"),
    path("reports/trial-balance/", views.trial_balance, name="trial_balance"),
    path("reports/income-statement/", views.income_statement, name="income_statement"),
    path("reports/balance-sheet/", views.balance_sheet, name="balance_sheet"),
    path("reports/inventory/", views.inventory_report, name="inventory_report"),
    path("accounts/<str:code>/", views.account_detail, name="account_detail"),
]