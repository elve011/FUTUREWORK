import logging

from common.envelope import build_envelope
from ports.factory import get_port
from .models import EmittedEvent

log = logging.getLogger(__name__)


def emit(type_, project_id, milestone_id, payload, correlation_id=None):
    """Store in the outbox, then try to publish to Dev 4. A publish failure never breaks the pipeline."""
    env = build_envelope(type_, project_id, milestone_id, payload, correlation_id)
    row = EmittedEvent.objects.create(event_id=env["eventId"], type=type_, project_id=project_id, envelope=env)
    try:
        get_port("events").publish(env)
        row.delivered = True
        row.save(update_fields=["delivered"])
    except Exception as exc:  # noqa: BLE001
        log.warning("event %s not delivered: %s", type_, exc)
    return env
