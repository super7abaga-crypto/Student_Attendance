from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from django.http import JsonResponse
from apps.core.frontend import asset, portal


def health(_request):
    return JsonResponse({"ok": True, "service": "learn2earn-attendance", "timezone": "Africa/Lagos"})


urlpatterns = [
    path("student/", TemplateView.as_view(template_name="student/index.html"), name="student-portal"),
    path("", portal, name="portal"),
    path("assets/<str:filename>", asset, name="asset-in-assets"),
    path("<str:filename>", asset, name="asset"),
    path("health/", health, name="health"),
    path("django-admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
]
