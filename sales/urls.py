from django.urls import path
from . import views

app_name = "sales"

urlpatterns = [
    path("new-sale/", views.new_sale, name="new_sale"),
]