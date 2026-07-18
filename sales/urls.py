from django.urls import path
from . import views

app_name = "sales"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("new-sale/", views.new_sale, name="new_sale"),
    path("sale/<int:pk>/receipt/", views.receipt, name="receipt"),
]