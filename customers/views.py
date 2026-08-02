from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError

from .models import Customer


def require_perm(perm):
    def decorator(view):
        @login_required
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perm(perm):
                messages.error(request, "You don't have permission to open that page.")
                return redirect("sales:dashboard")
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


@require_perm("customers.add_customer")
def new_customer(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Customer name is required.")
            return redirect("customers:new_customer")
        customer = Customer(
            name=name,
            phone=(request.POST.get("phone") or "").strip(),
            email=(request.POST.get("email") or "").strip(),
            address=(request.POST.get("address") or "").strip(),
            notes=(request.POST.get("notes") or "").strip(),
        )
        try:
            customer.save()
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("customers:new_customer")
        messages.success(request, f"Customer “{customer.name}” added.")
        return redirect("customers:new_customer")

    return render(request, "customers/new_customer.html", {
        "customers": Customer.objects.all().order_by("name"),
    })
