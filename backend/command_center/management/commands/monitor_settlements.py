"""Poll a configured read-only settlement source without Celery or signing."""

import hashlib
import json
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from command_center.adapters.settlement import SettlementSourceUnavailable, get_settlement_adapter
from command_center.models import EventOutbox, SettlementMonitorAttempt, SettlementRecord, WorkerLease, SystemEvent


MONITORED_STATUSES = (
    SettlementRecord.Status.SUBMITTED_BY_OWNER,
    SettlementRecord.Status.OBSERVED_PENDING,
    SettlementRecord.Status.UNKNOWN,
)
ALLOWED_OBSERVATION_STATUSES = {"PENDING", "CONFIRMED", "FAILED"}


def _canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class Command(BaseCommand):
    help = "Observe submitted settlements through a read-only adapter (no Celery, no signing)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Poll one bounded batch and exit.")
        parser.add_argument("--poll-interval", type=float, default=5.0)
        parser.add_argument("--lease-seconds", type=int, default=30)
        parser.add_argument("--batch-size", type=int, default=50)

    def handle(self, *args, **options):
        owner = uuid.uuid4().hex
        lease, _ = WorkerLease.objects.get_or_create(name="settlement-monitor")
        self._lease = lease
        self._owner = owner
        self._lease_seconds = max(5, options["lease_seconds"])
        now = timezone.now()
        acquired = WorkerLease.objects.filter(pk=lease.pk).filter(
            Q(expires_at__isnull=True) | Q(expires_at__lt=now)
        ).update(owner=owner, expires_at=now + timedelta(seconds=self._lease_seconds))
        if not acquired:
            self.stderr.write("Settlement monitor lease is held by another process; exiting.")
            return
        try:
            while True:
                count = self._poll_batch(max(1, min(options["batch_size"], 500)), options["poll_interval"])
                if options["once"]:
                    self.stdout.write(f"Checked {count} settlement(s).")
                    return
                self._refresh_lease()
                time.sleep(max(0.25, options["poll_interval"]))
        finally:
            WorkerLease.objects.filter(pk=lease.pk, owner=owner).update(owner="", expires_at=None)

    def _refresh_lease(self):
        WorkerLease.objects.filter(pk=self._lease.pk, owner=self._owner).update(
            expires_at=timezone.now() + timedelta(seconds=self._lease_seconds)
        )

    def _poll_batch(self, batch_size, poll_interval):
        now = timezone.now()
        due_before = now - timedelta(seconds=max(1.0, poll_interval))
        rows = list(
            SettlementRecord.objects.filter(status__in=MONITORED_STATUSES)
            .filter(Q(last_checked_at__isnull=True) | Q(last_checked_at__lte=due_before))
            .order_by("updated_at", "settlement_id")[:batch_size]
        )
        if not rows:
            return 0

        try:
            adapter = get_settlement_adapter(getattr(settings, "FW_MODE_SETTLEMENT", "local"))
        except SettlementSourceUnavailable:
            for row in rows:
                self._record_unavailable(row, "SOURCE_UNAVAILABLE", "unavailable")
            return len(rows)

        for row in rows:
            try:
                observation = adapter.observe(row)
                self._queue_observation(row, observation, getattr(adapter, "source", "settlement-source"))
            except SettlementSourceUnavailable:
                self._record_unavailable(row, "SOURCE_UNAVAILABLE", getattr(adapter, "source", "unavailable"))
            except (TypeError, ValueError, KeyError):
                self._record_attempt(row, SettlementMonitorAttempt.Outcome.INVALID, "INVALID_OBSERVATION", getattr(adapter, "source", "settlement-source"))
            except Exception:
                # Persist only a normalized code; provider exception text may contain credentials.
                self._record_attempt(row, SettlementMonitorAttempt.Outcome.ERROR, "SOURCE_ERROR", getattr(adapter, "source", "settlement-source"))
        self._refresh_lease()
        return len(rows)

    def _record_unavailable(self, settlement, error_code, source):
        self._record_attempt(settlement, SettlementMonitorAttempt.Outcome.UNAVAILABLE, error_code, source)

    def _record_attempt(self, settlement, outcome, error_code="", source=""):
        checked_at = timezone.now()
        with transaction.atomic():
            SettlementMonitorAttempt.objects.create(
                settlement=settlement,
                outcome=outcome,
                source=str(source)[:128],
                error_code=error_code,
                checked_at=checked_at,
            )
            SettlementRecord.objects.filter(pk=settlement.pk).update(last_checked_at=checked_at)

    def _queue_observation(self, settlement, observation, adapter_source):
        if observation is None:
            self._record_unavailable(settlement, "NO_OBSERVATION", adapter_source)
            return
        if not isinstance(observation, dict):
            raise TypeError("Adapter result must be an object.")
        status = str(observation.get("status", "")).upper()
        transaction_id = str(observation.get("transaction_id", ""))[:128]
        if status not in ALLOWED_OBSERVATION_STATUSES:
            raise ValueError("Unsupported settlement status.")
        if status in {"PENDING", "CONFIRMED", "FAILED"} and not transaction_id:
            transaction_id = settlement.transaction_id
        if status == "CONFIRMED":
            if not transaction_id or observation.get("finality_confirmed") is not True or not observation.get("consensus_timestamp"):
                raise ValueError("Confirmation requires transaction ID and source finality evidence.")
        source = str(observation.get("source") or adapter_source)[:128]
        network = str(observation.get("network") or "")[:40]
        payload = {
            "settlement_id": settlement.settlement_id,
            "status": status,
            "transaction_id": transaction_id,
            "network": network,
        }
        if status == "CONFIRMED":
            payload.update(finality_confirmed=True, consensus_timestamp=str(observation["consensus_timestamp"])[:64])
        fingerprint = _canonical_hash({"payload": payload, "source": source})
        event_id = f"settlement-observation-{fingerprint[:48]}"
        occurred_at_value = observation.get("observed_at")
        if not occurred_at_value:
            raise ValueError("Source observation timestamp is required.")
        occurred_at = parse_datetime(occurred_at_value) if isinstance(occurred_at_value, str) else occurred_at_value
        if occurred_at is None or timezone.is_naive(occurred_at):
            raise ValueError("Source observation timestamp must include a timezone.")

        with transaction.atomic():
            event, created = SystemEvent.objects.get_or_create(
                event_id=event_id,
                defaults={
                    "event_type": "HEDERA_TRANSACTION_OBSERVED",
                    "project_id": settlement.project_id,
                    "occurred_at": occurred_at,
                    "source": source,
                    "schema_version": "dev4-local/1.0",
                    "payload": payload,
                    "payload_sha256": _canonical_hash(payload),
                    "trace_id": f"FW-TRACE-{uuid.uuid4().hex[:24]}",
                    "status": SystemEvent.Status.RECEIVED,
                },
            )
            if created:
                EventOutbox.objects.create(event=event)
            SettlementMonitorAttempt.objects.create(
                settlement=settlement,
                outcome=SettlementMonitorAttempt.Outcome.OBSERVED,
                source=source,
                observed_status=status,
                transaction_id=transaction_id,
            )
            SettlementRecord.objects.filter(pk=settlement.pk).update(last_checked_at=timezone.now())
