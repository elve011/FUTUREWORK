from django.contrib import admin
from django.urls import include, path

from .health import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", health_check, name="health"),
    path("api/", include("project_catalog.urls")),
    path("", include("command_center.urls")),
]