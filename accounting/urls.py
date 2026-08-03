from django.urls import path
from . import views

app_name = "accounting"

urlpatterns = [
    path("journal-entry/new/", views.new_journal_entry, name="new_journal_entry"),
    path("reports/", views.reports_index, name="reports"),
    path("reports/export-all/<str:file_format>/", views.export_all_reports, name="export_all_reports"),
    path("reports/trial-balance/", views.trial_balance, name="trial_balance"),
    path("reports/income-statement/", views.income_statement, name="income_statement"),
    path("reports/balance-sheet/", views.balance_sheet, name="balance_sheet"),
    path("reports/inventory/", views.inventory_report, name="inventory_report"),
    path("reports/bank-movement/", views.bank_movement, name="bank_movement"),
    path("reports/gold-movement/", views.gold_movement, name="gold_movement"),
    path("accounts/<str:code>/", views.account_detail, name="account_detail"),
]
