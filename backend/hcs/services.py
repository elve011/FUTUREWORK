"""HCS anchoring: topic per project, idempotent submit, retry, Mirror Node readback."""
import json
import logging
import time

from django.conf import settings

from common.errors import ApiError
from ports.factory import get_port
from .models import HCSEvent, HCSTopic

log = logging.getLogger(__name__)


def get_or_create_topic(project_id: str) -> HCSTopic:
    topic = HCSTopic.objects.filter(project_id=project_id).first()
    if topic:
        return topic
    topic_id = get_port("hcs").create_topic(memo=project_id)
    return HCSTopic.objects.create(project_id=project_id, topic_id=topic_id)


def build_message(event_type, project_id, milestone_id, evidence_id, proof_hash) -> str:
    """Compact on purpose: hash + ids only, never the evidence body (HCS limit ~1 KB)."""
    msg = json.dumps({"v": 1, "t": event_type, "p": project_id, "m": milestone_id, "e": evidence_id, "h": proof_hash},
                     separators=(",", ":"), sort_keys=True)
    if len(msg.encode()) > settings.HCS_MAX_MESSAGE_BYTES:
        raise ApiError("HCS_MESSAGE_TOO_LARGE", "HCS message exceeds size budget", 422)
    return msg


def anchor(project_id, milestone_id, evidence_id, proof_hash, event_type="EVIDENCE_VERIFIED") -> HCSEvent:
    topic = get_or_create_topic(project_id)
    event, _ = HCSEvent.objects.get_or_create(
        topic=topic, event_type=event_type, proof_hash=proof_hash,
        defaults={"evidence_id": evidence_id, "milestone_id": milestone_id,
                  "message": build_message(event_type, project_id, milestone_id, evidence_id, proof_hash)})
    if event.status in (HCSEvent.Status.SUBMITTED, HCSEvent.Status.CONFIRMED):
        return event  # already on-chain: never submit twice
    return submit_event(event)


def submit_event(event: HCSEvent) -> HCSEvent:
    port = get_port("hcs")
    last = None
    for attempt in range(1, settings.HCS_MAX_RETRIES + 1):
        event.attempts += 1
        try:
            res = port.submit(event.topic.topic_id, event.message)
            event.sequence_number, event.transaction_id = res["sequenceNumber"], res["transactionId"]
            event.status, event.last_error = HCSEvent.Status.SUBMITTED, ""
            event.save()
            confirm_readback(event)
            return event
        except Exception as exc:  # noqa: BLE001 - network / SDK errors: retry then queue
            last = exc
            log.warning("HCS submit failed (%s/%s): %s", attempt, settings.HCS_MAX_RETRIES, exc)
            time.sleep(settings.HCS_RETRY_DELAY * attempt)
    event.status, event.last_error = HCSEvent.Status.QUEUED, str(last)
    event.save()
    return event


def confirm_readback(event: HCSEvent, attempts=None) -> HCSEvent:
    """Read the message back from the Mirror Node and compare hashes (FR-E-09)."""
    mirror = get_port("mirror")
    for _ in range(attempts or settings.MIRROR_POLL_ATTEMPTS):
        try:
            msg = mirror.get_message(event.topic.topic_id, event.sequence_number)
        except Exception as exc:  # noqa: BLE001
            log.warning("Mirror Node error: %s", exc)
            msg = None
        if msg:
            try:
                same = json.loads(msg["message"]).get("h") == event.proof_hash
            except ValueError:
                same = False
            event.consensus_timestamp = msg["consensusTimestamp"]
            event.readback_ok = same
            event.status = HCSEvent.Status.CONFIRMED if same else HCSEvent.Status.FAILED
            event.last_error = "" if same else "READBACK_MISMATCH"
            event.save()
            return event
        time.sleep(settings.MIRROR_POLL_DELAY)
    return event  # still SUBMITTED: shown as "pending" in the dashboard, retried by sync()


def sync() -> dict:
    """Retry QUEUED submits and finish pending readbacks. Run from /api/hcs/sync or `manage.py hcs_sync`."""
    resubmitted = readback = 0
    for e in HCSEvent.objects.filter(status=HCSEvent.Status.QUEUED).select_related("topic"):
        submit_event(e)
        resubmitted += 1
    for e in HCSEvent.objects.filter(status=HCSEvent.Status.SUBMITTED).select_related("topic"):
        confirm_readback(e, attempts=1)
        readback += 1
    return {"resubmitted": resubmitted, "readbackChecked": readback}
