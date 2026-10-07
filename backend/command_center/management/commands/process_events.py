"""Sequential durable event worker; intended to run as one supervised process."""

import time
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from command_center.mock_data import ensure_mock_agents
from command_center.adapters.evidence import EvidenceSourceError
from command_center.models import Agent, AgentAction, AgentExecution, AuditLog, EventOutbox, EvidenceSubmission, SystemEvent, WorkerLease
from command_center.orchestration import EVENT_AGENT_ROUTES, process_event
from command_center.agent_contracts import canonical_hash


class Command(BaseCommand):
    help = "Process durable event outbox sequentially (no Celery or broker)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process currently due events, then exit.")
        parser.add_argument("--poll-interval", type=float, default=0.5)
        parser.add_argument("--lease-seconds", type=int, default=30)
        parser.add_argument("--max-attempts", type=int, default=5)

    def handle(self, *args, **options):
        owner = uuid.uuid4().hex
        lease, _ = WorkerLease.objects.get_or_create(name="event-worker")
        self._lease = lease
        self._owner = owner
        self._lease_seconds = max(5, options["lease_seconds"])
        now = timezone.now()
        acquired = WorkerLease.objects.filter(pk=lease.pk).filter(
            Q(expires_at__isnull=True) | Q(expires_at__lt=now)
        ).update(owner=owner, expires_at=now + timedelta(seconds=self._lease_seconds))
        if not acquired:
            self.stderr.write("Worker lease is held by another process; exiting.")
            return
        try:
            ensure_mock_agents()
            while True:
                heartbeat_time = timezone.now()
                heartbeat_due = heartbeat_time - timedelta(seconds=10)
                Agent.objects.filter(Q(last_heartbeat_at__isnull=True) | Q(last_heartbeat_at__lt=heartbeat_due)).update(last_heartbeat_at=heartbeat_time)
                processed = self._process_due(max_attempts=max(1, options["max_attempts"]))
                if options["once"]:
                    self.stdout.write(f"Processed {processed} event(s).")
                    return
                self._refresh_lease()
                time.sleep(max(0.1, options["poll_interval"]))
        finally:
            WorkerLease.objects.filter(pk=lease.pk, owner=owner).update(owner="", expires_at=None)

    def _refresh_lease(self):
        WorkerLease.objects.filter(pk=self._lease.pk, owner=self._owner).update(
            expires_at=timezone.now() + timedelta(seconds=self._lease_seconds)
        )

    def _process_due(self, *, max_attempts):
        processed = 0
        while True:
            now = timezone.now()
            row = EventOutbox.objects.filter(
                Q(status__in=(EventOutbox.Status.PENDING, EventOutbox.Status.RETRY))
                | Q(status=EventOutbox.Status.PROCESSING, lease_until__lt=now),
                next_attempt_at__lte=now,
            ).select_related("event").order_by("created_at", "id").first()
            if row is None:
                return processed
            lease_until = now + timedelta(seconds=self._lease_seconds)
            try:
                with transaction.atomic():
                    row.status = EventOutbox.Status.PROCESSING
                    row.attempt_count += 1
                    row.lease_until = lease_until
                    row.save(update_fields=("status", "attempt_count", "lease_until", "updated_at"))
                # Keep the attempt durable before invoking orchestration so a crash
                # cannot reset retry accounting. Workflow writes and ACK are atomic.
                with transaction.atomic():
                    event = SystemEvent.objects.get(pk=row.event_id)
                    event.status = SystemEvent.Status.RUNNING
                    event.save(update_fields=("status",))
                    process_event(event.event_id)
                    event.refresh_from_db()
                    event.processed_at = timezone.now()
                    event.save(update_fields=("processed_at",))
                    row.status = EventOutbox.Status.PROCESSED
                    row.lease_until = None
                    row.last_error_code = ""
                    row.save(update_fields=("status", "lease_until", "last_error_code", "updated_at"))
                    AuditLog.objects.create(
                        event=event, project_id=event.project_id, trace_id=event.trace_id,
                        event_type=event.event_type, action="OUTBOX_PROCESSED",
                        status=row.status, details={"attempt": row.attempt_count},
                    )
                processed += 1
            except OperationalError as exc:
                if "locked" not in str(exc).lower():
                    self._record_failure(row.pk, "DATABASE_ERROR", max_attempts)
                else:
                    # SQLite has one writer. A short pause allows the active transaction to finish.
                    time.sleep(0.1)
                    self._record_failure(row.pk, "SQLITE_BUSY", max_attempts)
            except EvidenceSourceError as exc:
                # Provider errors are normalized codes, never response/token text.
                self._record_failure(row.pk, exc.code, max_attempts)
            except Exception:
                # Do not expose exception text: it may include user data.
                self._record_failure(row.pk, "WORKFLOW_ERROR", max_attempts)
            self._refresh_lease()

    def _record_failure(self, outbox_id, error_code, max_attempts):
        now = timezone.now()
        with transaction.atomic():
            row = EventOutbox.objects.select_related("event").get(pk=outbox_id)
            terminal = row.attempt_count >= max_attempts
            row.status = EventOutbox.Status.QUARANTINED if terminal else EventOutbox.Status.RETRY
            row.last_error_code = error_code
            row.lease_until = None
            row.next_attempt_at = now if terminal else now + timedelta(seconds=min(300, 2 ** row.attempt_count))
            row.save(update_fields=("status", "last_error_code", "lease_until", "next_attempt_at", "updated_at"))
            event = row.event
            event.status = SystemEvent.Status.FAILED if terminal else SystemEvent.Status.RECEIVED
            event.save(update_fields=("status",))
            if event.event_type == "EVIDENCE_REVIEW_REQUESTED":
                evidence_id = event.payload.get("evidence_id")
                if evidence_id:
                    EvidenceSubmission.objects.filter(
                        project__external_id=event.project_id,
                        evidence_id=evidence_id,
                        source="GITHUB_API",
                    ).update(status=EvidenceSubmission.Status.UNKNOWN, reasons=[error_code])
            agent_key = EVENT_AGENT_ROUTES.get(event.event_type)
            if event.event_type in {"AGENT_BLOCKED", "SYSTEM_ALERT_RAISED"}:
                agent_key = event.payload.get("agent_key")
            agent = Agent.objects.filter(key=agent_key or "").first()
            if agent:
                execution, _created = AgentExecution.objects.get_or_create(
                    agent=agent,
                    event=event,
                    defaults={"trace_id": event.trace_id, "started_at": event.received_at},
                )
                execution.agent_version = agent.agent_version
                execution.idempotency_key = f"{agent.key}:{event.event_id}"
                execution.status = AgentExecution.Status.PERMANENT_FAILURE if terminal else AgentExecution.Status.RETRYABLE_FAILURE
                execution.reason_code = error_code
                execution.source_refs = [event.event_id]
                execution.input_sha256 = canonical_hash(event.payload)
                execution.output = {"error_code": error_code}
                execution.finished_at = now
                execution.save()
                AgentAction.objects.update_or_create(
                    agent=agent,
                    event=event,
                    defaults={
                        "project_id": event.project_id,
                        "trace_id": event.trace_id,
                        "span_id": execution.span_id,
                        "action_type": "EXECUTE_EVENT",
                        "status": execution.status,
                        "summary": f"{agent.display_name}: {error_code}.",
                        "metadata": {"event_id": event.event_id, "agent_version": agent.agent_version, "reason_code": error_code},
                    },
                )
                agent.last_error_code = error_code
                agent.save(update_fields=("last_error_code", "updated_at"))
            AuditLog.objects.create(
                event=event, project_id=event.project_id, trace_id=event.trace_id,
                event_type=event.event_type, action="OUTBOX_QUARANTINED" if terminal else "OUTBOX_RETRY_SCHEDULED",
                status=row.status, details={"attempt": row.attempt_count, "error_code": error_code},
            )
