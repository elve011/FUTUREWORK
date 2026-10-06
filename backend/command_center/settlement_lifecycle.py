"""Append-only settlement state machine; Dev 4 observes and never submits."""

from django.db import transaction
from django.utils import timezone

from .models import AgentAlert, SettlementRecord, SettlementTransition, SystemEvent


OWNER_STATUS_MAP = {
    "PENDING": SettlementRecord.Status.OBSERVED_PENDING,
    "SUBMITTED": SettlementRecord.Status.SUBMITTED_BY_OWNER,
    "CONFIRMED": SettlementRecord.Status.CONFIRMED,
    "FAILED": SettlementRecord.Status.FAILED,
    "REVERSED": SettlementRecord.Status.FAILED,
}

ALLOWED_TRANSITIONS = {
    "": {SettlementRecord.Status.REQUESTED},
    SettlementRecord.Status.REQUESTED: {
        SettlementRecord.Status.POLICY_PENDING,
        SettlementRecord.Status.AUTHORIZED,
        SettlementRecord.Status.POLICY_BLOCKED,
        SettlementRecord.Status.UNKNOWN,
        SettlementRecord.Status.FAILED,
    },
    SettlementRecord.Status.POLICY_PENDING: {
        SettlementRecord.Status.AUTHORIZED,
        SettlementRecord.Status.POLICY_BLOCKED,
        SettlementRecord.Status.UNKNOWN,
        SettlementRecord.Status.FAILED,
    },
    SettlementRecord.Status.AUTHORIZED: {
        SettlementRecord.Status.SUBMITTED_BY_OWNER,
        SettlementRecord.Status.UNKNOWN,
    },
    SettlementRecord.Status.SUBMITTED_BY_OWNER: {
        SettlementRecord.Status.OBSERVED_PENDING,
        SettlementRecord.Status.CONFIRMED,
        SettlementRecord.Status.FAILED,
        SettlementRecord.Status.UNKNOWN,
    },
    SettlementRecord.Status.OBSERVED_PENDING: {
        SettlementRecord.Status.OBSERVED_PENDING,
        SettlementRecord.Status.CONFIRMED,
        SettlementRecord.Status.FAILED,
        SettlementRecord.Status.UNKNOWN,
    },
    SettlementRecord.Status.UNKNOWN: {
        SettlementRecord.Status.SUBMITTED_BY_OWNER,
        SettlementRecord.Status.OBSERVED_PENDING,
        SettlementRecord.Status.CONFIRMED,
        SettlementRecord.Status.FAILED,
        SettlementRecord.Status.UNKNOWN,
    },
    SettlementRecord.Status.CONFIRMED: set(),
    SettlementRecord.Status.FAILED: set(),
    SettlementRecord.Status.POLICY_BLOCKED: set(),
}


def _reported_target(event: SystemEvent, policy_decision=None):
    payload = event.payload if isinstance(event.payload, dict) else {}
    if event.event_type == "SETTLEMENT_REQUESTED":
        return SettlementRecord.Status.REQUESTED
    if event.event_type == "TRANSACTION_FAILED":
        return SettlementRecord.Status.FAILED
    if event.event_type == "HEDERA_ERROR":
        return SettlementRecord.Status.UNKNOWN
    if event.event_type == "POLICY_DECIDED":
        policy_decision = str(payload.get("decision", "")).upper()
        return {
            "ALLOW": SettlementRecord.Status.AUTHORIZED,
            "BLOCK": SettlementRecord.Status.POLICY_BLOCKED,
            "HUMAN_REVIEW": SettlementRecord.Status.POLICY_PENDING,
        }.get(policy_decision)
    if event.event_type == "POLICY_EVALUATION_REQUESTED":
        policy_decision = str(policy_decision or "HUMAN_REVIEW").upper()
        return {
            "ALLOW": SettlementRecord.Status.AUTHORIZED,
            "BLOCK": SettlementRecord.Status.POLICY_BLOCKED,
            "HUMAN_REVIEW": SettlementRecord.Status.POLICY_PENDING,
        }.get(policy_decision)
    if event.event_type in {"SETTLEMENT_UPDATED", "HEDERA_TRANSACTION_OBSERVED"}:
        return OWNER_STATUS_MAP.get(str(payload.get("status", "")).upper())
    return None


def apply_settlement_event(event: SystemEvent, *, policy_decision=None):
    """Persist a valid transition once; return a safe, typed agent result."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    settlement_id = payload.get("settlement_id")
    target = _reported_target(event, policy_decision=policy_decision)
    if not settlement_id:
        return {"status": "BLOCKED", "reason_code": "SETTLEMENT_REFERENCE_MISSING", "settlement_id": None}
    if target is None:
        return {"status": "BLOCKED", "reason_code": "SETTLEMENT_STATUS_UNSUPPORTED", "settlement_id": settlement_id}

    transaction_id = str(payload.get("transaction_id") or "")[:128]
    if target == SettlementRecord.Status.CONFIRMED and not transaction_id:
        return {"status": "BLOCKED", "reason_code": "CONFIRMATION_TRANSACTION_ID_REQUIRED", "settlement_id": settlement_id}
    if target == SettlementRecord.Status.CONFIRMED and (
        payload.get("finality_confirmed") is not True or not payload.get("consensus_timestamp")
    ):
        return {"status": "BLOCKED", "reason_code": "FINALITY_EVIDENCE_REQUIRED", "settlement_id": settlement_id}

    with transaction.atomic():
        record = SettlementRecord.objects.filter(settlement_id=settlement_id).first()
        if record is None:
            if target != SettlementRecord.Status.REQUESTED:
                return {"status": "BLOCKED", "reason_code": "SETTLEMENT_REQUEST_NOT_FOUND", "settlement_id": settlement_id}
            record = SettlementRecord.objects.create(
                settlement_id=settlement_id,
                project_id=event.project_id,
                trace_id=event.trace_id,
                status=SettlementRecord.Status.REQUESTED,
                source=event.source,
            )
            previous = ""
        else:
            if record.project_id != event.project_id:
                return {"status": "BLOCKED", "reason_code": "SETTLEMENT_PROJECT_MISMATCH", "settlement_id": settlement_id}
            previous = record.status

        existing_transition = SettlementTransition.objects.filter(settlement=record, event=event).first()
        if existing_transition:
            return {
                "status": "SUCCEEDED",
                "reason_code": existing_transition.reason_code or "SETTLEMENT_EVENT_ALREADY_APPLIED",
                "settlement_id": settlement_id,
                "current_status": record.status,
            }

        if target not in ALLOWED_TRANSITIONS.get(previous, set()):
            return {
                "status": "BLOCKED",
                "reason_code": "ILLEGAL_SETTLEMENT_TRANSITION",
                "settlement_id": settlement_id,
                "current_status": previous,
                "reported_status": target,
            }

        # Creation is itself the REQUESTED transition; do not add it a second time.
        if previous == "":
            previous = SettlementRecord.Status.REQUESTED
        else:
            record.status = target
        record.transaction_id = transaction_id or record.transaction_id
        if target == SettlementRecord.Status.CONFIRMED:
            record.consensus_timestamp = str(payload.get("consensus_timestamp") or "")[:64]
        record.source = event.source
        record.network = str(payload.get("network") or record.network)[:40]
        if event.event_type in {"SETTLEMENT_UPDATED", "HEDERA_TRANSACTION_OBSERVED", "TRANSACTION_FAILED"}:
            record.last_observed_at = event.occurred_at
        record.last_error_code = ""
        record.save(update_fields=("status", "transaction_id", "consensus_timestamp", "source", "network", "last_observed_at", "last_error_code", "updated_at"))
        SettlementTransition.objects.create(
            settlement=record,
            event=event,
            from_status="" if previous == SettlementRecord.Status.REQUESTED and target == previous else previous,
            to_status=target,
            source=event.source,
            transaction_id=transaction_id,
            consensus_timestamp=str(payload.get("consensus_timestamp") or "")[:64],
            reason_code="SOURCE_EVENT_OBSERVED",
            observed_at=event.occurred_at,
        )
        if target in {SettlementRecord.Status.FAILED, SettlementRecord.Status.POLICY_BLOCKED}:
            alert_type = "SETTLEMENT_FAILED" if target == SettlementRecord.Status.FAILED else "SETTLEMENT_POLICY_BLOCKED"
            AgentAlert.objects.get_or_create(
                alert_type=alert_type,
                project_id=event.project_id,
                trace_id=event.trace_id,
                defaults={
                    "severity": AgentAlert.Severity.HIGH,
                    "title": "Settlement failure" if target == SettlementRecord.Status.FAILED else "Settlement blocked by policy",
                    "details": {"settlement_id": settlement_id, "event_id": event.event_id, "reason_code": "SETTLEMENT_STATUS_OBSERVED"},
                },
            )
        return {"status": "SUCCEEDED", "reason_code": "SOURCE_EVENT_OBSERVED", "settlement_id": settlement_id, "current_status": target}
