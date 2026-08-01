from django.urls import path
from . import views

app_name = "purchases"

urlpatterns = [
    path("new-supplier/", views.new_supplier, name="new_supplier"),
    path("new-purchase/", views.new_purchase, name="new_purchase"),
]