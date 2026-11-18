from django.contrib import admin
from django.http import HttpResponse
from django.urls import path

from complaints import api


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz", healthz),
    path("api/complaints/", api.create_complaint, name="api-create-complaint"),
    # The staff portal is the whole site.
    path("", admin.site.urls),
]
