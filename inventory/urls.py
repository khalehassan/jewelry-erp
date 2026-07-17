from django.urls import path
from . import views

app_name = "inventory"

urlpatterns = [
    path("import-stock/", views.import_stock, name="import_stock"),
]