from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("sales.urls")),
    path("", include("inventory.urls")),
    path("", include("purchases.urls")),
    path("", include("accounting.urls")),
]