"""Small data-minimization helpers for event payloads."""

import hashlib
import json
from django.core.serializers.json import DjangoJSONEncoder


SENSITIVE_KEY_PARTS = ("password", "secret", "token", "private_key", "privatekey", "api_key", "apikey")


def canonical_payload_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, cls=DjangoJSONEncoder).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def redact_sensitive(value):
    """Return a JSON-safe copy with credential-like fields redacted recursively."""
    if isinstance(value, dict):
        sanitized = {}
        for key, child in value.items():
            normalized_key = str(key).lower().replace("-", "_")
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = redact_sensitive(child)
        return sanitized
    if isinstance(value, list):
        return [redact_sensitive(child) for child in value]
    return value
