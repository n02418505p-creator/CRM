from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.urls import include, path

from complaints import api


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz", healthz),
    path("api/complaints/", api.create_complaint, name="api-create-complaint"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html", redirect_authenticated_user=True),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Django admin: used only for staff accounts and raw records.
    path("admin/", admin.site.urls),
    # The complaints portal.
    path("", include("complaints.urls")),
]
