"""Webhook ingestion: idempotent delivery -> normalize -> persist GitHub records -> Evidence -> (auto) verify."""
import logging

from django.conf import settings

from domain.normalize import normalize_pull_request, normalize_push, normalize_review
from evidence import services as evidence_services
from .models import CodeReview, GitHubCommit, GitHubRepository, PullRequest, WebhookDelivery

log = logging.getLogger(__name__)
NORMALIZERS = {"push": normalize_push, "pull_request": normalize_pull_request, "pull_request_review": normalize_review}


def _record(repo, n):
    dt = evidence_services.parse_dt(n["occurred_at"])
    m = n["metadata"]
    if n["source"] == "COMMIT":
        GitHubCommit.objects.get_or_create(repo=repo, sha=n["source_ref"], defaults={
            "message": n["title"], "author": n["author"], "branch": n["branch"], "committed_at": dt,
            "files_changed": m.get("files_changed") or 0, "milestone_id": n["milestone_id"]})
    elif n["source"] == "PULL_REQUEST":
        PullRequest.objects.update_or_create(repo=repo, number=m["number"], defaults={
            "title": n["title"], "author": n["author"], "branch": n["branch"], "merged": True,
            "additions": m.get("additions"), "deletions": m.get("deletions"), "labels": m.get("labels", []),
            "merged_at": dt, "milestone_id": n["milestone_id"]})
    elif n["source"] == "REVIEW":
        CodeReview.objects.get_or_create(repo=repo, review_id=int(n["source_ref"].rsplit("/", 1)[1]), defaults={
            "pr_number": m["number"], "reviewer": n["author"], "state": m.get("state", ""), "submitted_at": dt,
            "milestone_id": n["milestone_id"]})


def handle_delivery(delivery_id: str, event_type: str, payload: dict) -> dict:
    full_name = (payload.get("repository") or {}).get("full_name", "")
    delivery, created = WebhookDelivery.objects.get_or_create(
        delivery_id=delivery_id, defaults={"event_type": event_type, "repository": full_name, "payload": payload})
    if not created:
        return {"status": "duplicate", "deliveryId": delivery_id}  # replayed webhook: no double anchor

    def done(outcome, **extra):
        delivery.outcome = outcome
        delivery.save(update_fields=["outcome"])
        return {"status": outcome, "deliveryId": delivery_id, **extra}

    if event_type == "ping":
        return done("pong")
    repo = GitHubRepository.objects.filter(full_name=full_name).first()
    if repo is None:
        return done("ignored_unknown_repository")
    normalizer = NORMALIZERS.get(event_type)
    if normalizer is None:
        return done("ignored_event")

    try:
        collected = []
        for n in normalizer(payload):
            _record(repo, n)
            ev, new = evidence_services.collect(repo.project_id, n, expected_author=repo.worker_github)
            if new:
                collected.append(ev)
    except Exception:
        delivery.delete()  # let GitHub redeliver after a crash
        raise

    for ev in collected:  # verification errors must not fail the webhook response
        if settings.AUTO_VERIFY and ev.attached:
            try:
                evidence_services.process(ev)
            except Exception:  # noqa: BLE001
                log.exception("auto-verify failed for %s", ev.evidence_id)
    return done("processed", evidence=[e.evidence_id for e in collected])


def backfill(project_id: str) -> dict:
    """Pull existing GitHub activity (same pipeline as webhooks, idempotent via synthetic delivery ids)."""
    from ports.factory import get_port
    repos = list(GitHubRepository.objects.filter(project_id=project_id))
    if not repos:
        from common.errors import ApiError
        raise ApiError("REPO_NOT_CONNECTED", f"No GitHub repository connected to {project_id}", 404)
    port, summary = get_port("github"), {"repositories": [], "processed": 0, "duplicates": 0, "evidence": []}
    for repo in repos:
        for event, payload, delivery_id in port.fetch_activity(repo.full_name):
            res = handle_delivery(f"{delivery_id}", event, payload)
            summary["processed" if res["status"] == "processed" else "duplicates"] += 1
            summary["evidence"] += res.get("evidence", [])
        summary["repositories"].append(repo.full_name)
    return summary
