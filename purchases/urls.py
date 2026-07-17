from django.urls import path
from . import views

app_name = "purchases"

urlpatterns = [
    path("new-purchase/", views.new_purchase, name="new_purchase"),
]