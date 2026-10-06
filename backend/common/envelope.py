"""Standard event envelope (spec section 26)."""
import uuid
from datetime import datetime, timezone


def build_envelope(type_, project_id, milestone_id, payload, correlation_id=None):
    now = datetime.now(timezone.utc)
    return {
        "eventId": f"EVT-{now:%Y%m%d}-{uuid.uuid4().hex[:8]}",
        "type": type_,
        "version": "1.0",
        "occurredAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "producer": "evidence",
        "projectId": project_id,
        "milestoneId": milestone_id,
        "correlationId": correlation_id or f"c-{uuid.uuid4().hex[:8]}",
        "payload": payload,
    }
