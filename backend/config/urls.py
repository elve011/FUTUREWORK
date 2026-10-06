from django.urls import include, path

urlpatterns = [path("", include("command_center.urls"))]
