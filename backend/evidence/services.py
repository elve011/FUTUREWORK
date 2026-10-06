"""Evidence pipeline: collect -> verify (agent) -> proof hash -> HCS anchor -> events."""
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.db import transaction

from agent import evidence_agent
from common.errors import ApiError
from domain.canonical import proof_hash as compute_proof_hash
from hcs import services as hcs_services
from hcs.models import HCSEvent
from ports.factory import get_port
from .events import emit
from .models import Evidence, EvidenceHash, EvidenceVerification

log = logging.getLogger(__name__)


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def collect(project_id, n: dict, expected_author: str = ""):
    """Create Evidence from a normalized dict. Idempotent on (project, source, source_ref). Returns (evidence, created)."""
    with transaction.atomic():
        ev, created = Evidence.objects.get_or_create(
            project_id=project_id, source=n["source"], source_ref=n["source_ref"],
            defaults={
                "milestone_id": n.get("milestone_id"), "milestone_source": n.get("milestone_source") or "",
                "author": n["author"], "title": n.get("title", "")[:300], "content_digest": n["content_digest"],
                "occurred_at": parse_dt(n["occurred_at"]),
                "metadata": {**n.get("metadata", {}), "expected_author": expected_author},
            })
    if created:
        emit("EVIDENCE_COLLECTED", project_id, ev.milestone_id,
             {"evidenceId": ev.evidence_id, "source": ev.source, "milestoneId": ev.milestone_id})
    return ev, created


def features_for(ev: Evidence) -> dict:
    m = ev.metadata
    add, dele = m.get("additions"), m.get("deletions")
    expected = m.get("expected_author")
    author_ok = None if (ev.source in ("REVIEW", "MANUAL") or not expected) else ev.author.lower() == expected.lower()
    return {
        "attached": ev.attached, "author_ok": author_ok,
        "lines_changed": None if add is None or dele is None else add + dele,
        "tests_touched": m.get("tests_touched"), "message_ok": m.get("message_ok", False),
        "reviewed_or_merged": m.get("reviewed_or_merged", False), "ci_status": m.get("ci_status"),
    }


def attach(ev: Evidence, milestone_id: str) -> Evidence:
    if ev.status in (Evidence.Status.VERIFIED, Evidence.Status.ANCHORED):
        raise ApiError("EVIDENCE_LOCKED", "Verified evidence cannot be re-attached (its hash would change)", 409)
    ev.milestone_id, ev.milestone_source = milestone_id.upper(), "manual"
    ev.save()
    return ev


def _mark_anchored(ev: Evidence, event: HCSEvent):
    if ev.status != Evidence.Status.ANCHORED and event.status in (HCSEvent.Status.SUBMITTED, HCSEvent.Status.CONFIRMED):
        ev.status = Evidence.Status.ANCHORED
        ev.save(update_fields=["status", "updated_at"])
        emit("HCS_EVENT_SUBMITTED", ev.project_id, ev.milestone_id,
             {"topicId": event.topic.topic_id, "sequenceNumber": event.sequence_number,
              "consensusTimestamp": event.consensus_timestamp or None, "evidenceId": ev.evidence_id})


def process(ev: Evidence) -> Evidence:
    """Full pipeline for one evidence. Safe to call twice (idempotent)."""
    if not ev.attached:
        raise ApiError("EVIDENCE_NOT_ATTACHED", "Evidence is not linked to a milestone", 409,
                       {"evidenceId": ev.evidence_id})
    if ev.status == Evidence.Status.ANCHORED:
        return ev
    if ev.status != Evidence.Status.VERIFIED:  # VERIFIED but not anchored -> skip straight to anchoring
        ev.status = Evidence.Status.VERIFYING
        ev.save(update_fields=["status", "updated_at"])
        milestone = get_port("project").get_milestone(ev.project_id, ev.milestone_id)
        result = evidence_agent.run({"features": features_for(ev), "milestone": milestone,
                                     "threshold": settings.COMPLIANCE_THRESHOLD})
        EvidenceVerification.objects.create(evidence=ev, score=result["score"], verdict=result["verdict"],
                                            method=result["method"], reasons=result["reasons"])
        if result["verdict"] == "REJECTED":
            ev.status = Evidence.Status.REJECTED
            ev.save(update_fields=["status", "updated_at"])
            emit("EVIDENCE_REJECTED", ev.project_id, ev.milestone_id,
                 {"evidenceId": ev.evidence_id, "complianceScore": result["score"], "blockers": result["blockers"]})
            return ev
        proof = compute_proof_hash(ev.hashable())
        EvidenceHash.objects.update_or_create(evidence=ev, defaults={"proof_hash": proof})
        ev.status = Evidence.Status.VERIFIED
        ev.save(update_fields=["status", "updated_at"])
        emit("EVIDENCE_VERIFIED", ev.project_id, ev.milestone_id,
             {"evidenceId": ev.evidence_id, "complianceScore": result["score"], "proofHash": proof})

    proof = ev.proof.proof_hash
    event = hcs_services.anchor(ev.project_id, ev.milestone_id, ev.evidence_id, proof)
    _mark_anchored(ev, event)
    ev.refresh_from_db()
    return ev


def reconcile_anchored() -> int:
    """After hcs sync: mark VERIFIED evidence as ANCHORED once its HCS event went through."""
    n = 0
    for ev in Evidence.objects.filter(status=Evidence.Status.VERIFIED):
        event = HCSEvent.objects.filter(evidence_id=ev.evidence_id).first()
        if event:
            _mark_anchored(ev, event)
            n += 1
    return n
