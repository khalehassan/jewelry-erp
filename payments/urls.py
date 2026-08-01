from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("payments/", views.payments_page, name="payments"),
]
