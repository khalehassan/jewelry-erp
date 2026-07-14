from django.shortcuts import render

from inventory.models import JewelryItem


def new_sale(request):
    items = JewelryItem.objects.all()
    return render(request, "sales/new_sale.html", {"items": items})