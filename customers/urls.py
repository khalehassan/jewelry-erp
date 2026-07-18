from django.urls import path
from . import views

app_name = "customers"

urlpatterns = [
    path("new-customer/", views.new_customer, name="new_customer"),
]