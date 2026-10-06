"""Standard error format (spec 25.5)."""
from uuid import uuid4

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler


class ApiError(Exception):
    def __init__(self, code, message, status=400, details=None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details or {}


def _body(code, message, details, trace):
    return {"error": {"code": code, "message": message, "details": details, "traceId": trace}}


def handler(exc, context):
    trace = uuid4().hex
    if isinstance(exc, ApiError):
        return Response(_body(exc.code, exc.message, exc.details, trace), status=exc.status)
    resp = drf_handler(exc, context)
    if resp is None:
        return None
    code = "VALIDATION_ERROR" if resp.status_code == 400 else f"HTTP_{resp.status_code}"
    details = resp.data if isinstance(resp.data, dict) else {"detail": resp.data}
    message = str(details["detail"]) if "detail" in details else "Invalid request"
    resp.data = _body(code, message, details, trace)
    return resp
