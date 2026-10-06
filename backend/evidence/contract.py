"""Evidence Contract v1.0 (spec 25.2). Consumed by Dev 3 and Dev 4."""
from common.errors import ApiError
from hcs.models import HCSEvent
from .models import Evidence


def build_contract(milestone_id: str, project_id: str | None = None) -> dict:
    qs = Evidence.objects.filter(milestone_id=milestone_id.upper())
    if project_id:
        qs = qs.filter(project_id=project_id)
    good = qs.filter(status__in=[Evidence.Status.VERIFIED, Evidence.Status.ANCHORED]).order_by("-occurred_at")
    ev = good.first() or qs.order_by("-occurred_at").first()
    if ev is None:
        raise ApiError("EVIDENCE_NOT_FOUND", f"No evidence for milestone {milestone_id}", 404)
    v, proof = ev.latest_verification(), getattr(ev, "proof", None)
    hcs = HCSEvent.objects.filter(evidence_id=ev.evidence_id).select_related("topic").first()
    commit = ev.source_ref[:7] if ev.source == "COMMIT" else (ev.metadata.get("merge_commit_sha") or "")[:7] or None
    return {
        "projectId": ev.project_id, "milestoneId": ev.milestone_id, "evidenceId": ev.evidence_id,
        "verified": ev.status in (Evidence.Status.VERIFIED, Evidence.Status.ANCHORED),
        "complianceScore": v.score if v else None,
        "proofHash": proof.proof_hash if proof else None, "githubCommit": commit,
        "topicId": hcs.topic.topic_id if hcs else None,
        "sequenceNumber": hcs.sequence_number if hcs else None,
        "consensusTimestamp": (hcs.consensus_timestamp or None) if hcs else None,
    }
