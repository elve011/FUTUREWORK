from django.conf import settings
from django.http import JsonResponse


def health(request):
    return JsonResponse({"status": "ok", "module": "evidence", "mode": settings.FW_MODE})
