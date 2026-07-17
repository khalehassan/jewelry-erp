from django.urls import path
from . import views

app_name = "accounting"

urlpatterns = [
    path("reports/", views.reports, name="reports"),
    path("accounts/<str:code>/", views.account_detail, name="account_detail"),
]