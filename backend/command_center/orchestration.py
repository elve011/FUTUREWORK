"""Deterministic, auditable LangGraph workflow for accepted system events.

This is orchestration, not an autonomous payment agent: it routes, applies a
conservative policy gate, and records outcomes. It never signs or submits a
Hedera transaction.
"""

from typing import NotRequired, TypedDict

from django.db import transaction
from django.utils import timezone
from langgraph.graph import END, START, StateGraph

from .models import (
    Agent,
    AgentAction,
    AgentAlert,
    AgentDecision,
    AgentExecution,
    AuditLog,
    SystemEvent,
)
from .agent_contracts import AGENT_CONTRACT_VERSION, canonical_hash, execute_agent
from .settlement_lifecycle import apply_settlement_event


EVENT_AGENT_ROUTES = {
    "ENGAGEMENT_CREATED": "planner",
    "WORK_CREATED": "planner",
    "WORK_UNIT_COMPLETED": "planner",
    "MILESTONE_COMPLETED": "planner",
    "MILESTONE_DELAYED": "planner",
    "EVIDENCE_SUBMITTED": "evidence",
    "EVIDENCE_REVIEW_REQUESTED": "evidence",
    "EVIDENCE_VERIFIED": "evidence",
    "EVIDENCE_MISSING": "evidence",
    "POLICY_DECIDED": "risk",
    "POLICY_EVALUATION_REQUESTED": "risk",
    "HIGH_RISK": "risk",
    "SETTLEMENT_REQUESTED": "settlement",
    "SETTLEMENT_UPDATED": "settlement",
    "TRANSACTION_FAILED": "settlement",
    "HEDERA_TRANSACTION_OBSERVED": "settlement",
    "HEDERA_ERROR": "settlement",
}

ALERT_EVENT_TYPES = {
    "MILESTONE_DELAYED": (AgentAlert.Severity.WARNING, "Milestone en retard"),
    "EVIDENCE_MISSING": (AgentAlert.Severity.WARNING, "Preuve manquante"),
    "HIGH_RISK": (AgentAlert.Severity.HIGH, "Risque élevé"),
    "TRANSACTION_FAILED": (AgentAlert.Severity.CRITICAL, "Transaction échouée"),
    "AGENT_BLOCKED": (AgentAlert.Severity.HIGH, "Agent bloqué"),
    "HEDERA_ERROR": (AgentAlert.Severity.CRITICAL, "Erreur Hedera"),
}

VALID_DECISIONS = {choice for choice, _label in AgentDecision.Decision.choices}


class WorkflowState(TypedDict):
    event_id: str
    agent_key: NotRequired[str]
    decision: NotRequired[str]
    reason_code: NotRequired[str]
    reason: NotRequired[str]
    result_status: NotRequired[str]
    agent_result: NotRequired[dict]


def _resolve_agent(state: WorkflowState):
    event = SystemEvent.objects.get(event_id=state["event_id"])
    agent_key = EVENT_AGENT_ROUTES.get(event.event_type)
    if event.event_type == "AGENT_BLOCKED":
        agent_key = event.payload.get("agent_key")
    elif event.event_type == "SYSTEM_ALERT_RAISED":
        agent_key = event.payload.get("agent_key")
    return {"agent_key": agent_key or "", "result_status": "ROUTED" if agent_key else "UNROUTED"}


def _execute_agent(state: WorkflowState):
    event = SystemEvent.objects.get(event_id=state["event_id"])
    agent_key = state.get("agent_key", "")
    if not agent_key:
        return {"agent_result": {"agent_key": "", "agent_version": AGENT_CONTRACT_VERSION, "status": "PERMANENT_FAILURE", "reason_code": "NO_AGENT_ROUTE", "output": {}, "source_refs": [event.event_id]}}
    result = execute_agent(agent_key, event).as_dict()
    if agent_key == "settlement" or (event.event_type == "POLICY_DECIDED" and event.payload.get("settlement_id")):
        lifecycle_result = apply_settlement_event(event)
        if agent_key == "settlement" or lifecycle_result["status"] == "BLOCKED":
            result["status"] = lifecycle_result["status"]
            result["reason_code"] = lifecycle_result["reason_code"]
        result["output"]["lifecycle"] = lifecycle_result
    elif event.event_type == "POLICY_EVALUATION_REQUESTED" and event.payload.get("settlement_id"):
        policy_decision = result.get("output", {}).get("decision", "HUMAN_REVIEW")
        lifecycle_result = apply_settlement_event(event, policy_decision=policy_decision)
        if agent_key == "settlement" or lifecycle_result["status"] == "BLOCKED":
            result["status"] = lifecycle_result["status"]
            result["reason_code"] = lifecycle_result["reason_code"]
        result["output"]["lifecycle"] = lifecycle_result
    return {"agent_result": result}


def _apply_policy(state: WorkflowState):
    event = SystemEvent.objects.get(event_id=state["event_id"])
    if event.event_type == "POLICY_DECIDED":
        proposed = str(state.get("agent_result", {}).get("output", {}).get("decision", "HUMAN_REVIEW")).upper()
        decision = proposed if proposed in VALID_DECISIONS else "HUMAN_REVIEW"
        reason_code = str(state.get("agent_result", {}).get("reason_code", "POLICY_REASON_NOT_PROVIDED"))[:80]
        reason = str(event.payload.get("reason", "Décision reçue via l'événement policy."))[:500]
    elif event.event_type == "POLICY_EVALUATION_REQUESTED":
        output = state.get("agent_result", {}).get("output", {})
        proposed = str(output.get("decision", "HUMAN_REVIEW")).upper()
        decision = proposed if proposed in VALID_DECISIONS else "HUMAN_REVIEW"
        reasons = output.get("reason_codes") or ["POLICY_REASON_NOT_PROVIDED"]
        reason_code = str(reasons[0])[:80]
        reason = "; ".join(str(item) for item in reasons)[:500]
    elif event.event_type == "SETTLEMENT_REQUESTED":
        # No release or transfer is performed here. A separate, attributable
        # policy decision must be integrated before any critical action.
        decision = "HUMAN_REVIEW"
        reason_code = "POLICY_EVIDENCE_REQUIRED"
        reason = "Settlement reçu; en attente de la décision policy convenue et/ou d'une validation humaine."
    elif event.event_type == "HIGH_RISK":
        decision = "HUMAN_REVIEW"
        reason_code = "AUTHORITATIVE_POLICY_NOT_RECEIVED"
        reason = "Risque signalé; aucune décision policy autoritative n'a été fournie."
    else:
        decision = "PENDING"
        reason_code = "NO_CRITICAL_ACTION"
        reason = "Événement observé; aucune action critique n'est autorisée par cette étape."
    result_status = "BLOCKED" if decision in {"BLOCK", "HUMAN_REVIEW"} else "ROUTED"
    return {
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "result_status": result_status,
    }


def _persist_outcome_legacy(state: WorkflowState):
    event = SystemEvent.objects.get(event_id=state["event_id"])
    agent = Agent.objects.filter(key=state.get("agent_key", "")).first()
    now = timezone.now()

    if agent is None:
        event.status = SystemEvent.Status.BLOCKED
        event.save(update_fields=["status"])
        alert_type = "AGENT_BLOCKED" if event.event_type == "AGENT_BLOCKED" else "UNROUTED_EVENT"
        AgentAlert.objects.get_or_create(
            alert_type=alert_type,
            project_id=event.project_id,
            trace_id=event.trace_id,
            defaults={
                "severity": AgentAlert.Severity.HIGH,
                "title": "Événement sans agent correspondant",
                "details": {"event_id": event.event_id, "event_type": event.event_type},
            },
        )
        AuditLog.objects.create(
            event=event,
            project_id=event.project_id,
            trace_id=event.trace_id,
            event_type=event.event_type,
            action="EVENT_ROUTING_FAILED",
            status=SystemEvent.Status.BLOCKED,
            decision="BLOCK",
            details={"reason_code": "AGENT_NOT_FOUND"},
        )
        return {"result_status": "BLOCKED", "agent_key": "", "decision": "BLOCK"}

    decision_agent = Agent.objects.get(key="risk") if state["decision"] in {"ALLOW", "BLOCK", "HUMAN_REVIEW"} else agent
    execution_status = (
        AgentExecution.Status.BLOCKED
        if state["decision"] in {"BLOCK", "HUMAN_REVIEW"}
        else AgentExecution.Status.COMPLETED
    )
    event_status = SystemEvent.Status.BLOCKED if execution_status == AgentExecution.Status.BLOCKED else SystemEvent.Status.COMPLETED

    with transaction.atomic():
        execution = AgentExecution.objects.create(
            agent=agent,
            event=event,
            trace_id=event.trace_id,
            status=AgentExecution.Status.RUNNING,
            started_at=now,
        )
        AgentAction.objects.create(
            agent=agent,
            event=event,
            project_id=event.project_id,
            trace_id=event.trace_id,
            span_id=execution.span_id,
            action_type="ROUTE_EVENT",
            status=execution_status,
            summary=f"Événement {event.event_type} routé vers {agent.display_name}.",
            metadata={"event_id": event.event_id},
        )
        AgentDecision.objects.create(
            agent=decision_agent,
            event=event,
            project_id=event.project_id,
            trace_id=event.trace_id,
            decision=state["decision"],
            reason_code=state["reason_code"],
            reason=state["reason"],
            policy_version=str(event.payload.get("policy_version", ""))[:40],
            decided_by=event.source if event.event_type == "POLICY_DECIDED" else "dev4-policy-gate",
        )
        execution.status = execution_status
        execution.finished_at = timezone.now()
        execution.save(update_fields=["status", "finished_at"])
        event.status = event_status
        event.save(update_fields=["status"])
        agent.last_activity_at = now
        agent.status = Agent.Status.IDLE
        agent.save(update_fields=["last_activity_at", "status", "updated_at"])

        AuditLog.objects.create(
            event=event,
            project_id=event.project_id,
            trace_id=event.trace_id,
            span_id=execution.span_id,
            actor_type="AGENT",
            actor_id=agent.key,
            event_type=event.event_type,
            action="AGENT_EVENT_ROUTED",
            status=execution_status,
            decision=state["decision"],
            details={"reason_code": state["reason_code"]},
        )

        alert_info = ALERT_EVENT_TYPES.get(event.event_type)
        if alert_info:
            severity, title = alert_info
            AgentAlert.objects.get_or_create(
                alert_type=event.event_type,
                project_id=event.project_id,
                trace_id=event.trace_id,
                defaults={
                    "severity": severity,
                    "title": title,
                    "details": {"event_id": event.event_id, "source": event.source},
                },
            )

    return {
        "result_status": event_status,
        "agent_key": agent.key,
        "decision": state["decision"],
    }


def _persist_outcome(state: WorkflowState):
    """Persist one versioned agent result and its policy projection idempotently."""
    event = SystemEvent.objects.get(event_id=state["event_id"])
    agent = Agent.objects.filter(key=state.get("agent_key", "")).first()
    if agent is None:
        return _persist_outcome_legacy(state)

    result = state.get("agent_result", {})
    decision_agent = Agent.objects.get(key="risk") if state["decision"] in {"ALLOW", "BLOCK", "HUMAN_REVIEW"} else agent
    blocked = result.get("status") == "BLOCKED" or state["decision"] in {"BLOCK", "HUMAN_REVIEW"}
    execution_status = AgentExecution.Status.BLOCKED if blocked else AgentExecution.Status.COMPLETED
    event_status = SystemEvent.Status.BLOCKED if blocked else SystemEvent.Status.COMPLETED
    now = timezone.now()

    with transaction.atomic():
        execution, _created = AgentExecution.objects.get_or_create(
            agent=agent,
            event=event,
            defaults={"trace_id": event.trace_id, "status": AgentExecution.Status.RUNNING, "started_at": now},
        )
        execution.trace_id = event.trace_id
        execution.agent_version = result.get("agent_version", AGENT_CONTRACT_VERSION)
        execution.idempotency_key = f"{agent.key}:{event.event_id}"
        execution.status = AgentExecution.Status.RUNNING
        execution.started_at = execution.started_at or now
        execution.reason_code = result.get("reason_code", state["reason_code"])
        execution.source_refs = result.get("source_refs", [event.event_id])
        execution.input_sha256 = canonical_hash(event.payload)
        execution.output = result.get("output", {})
        execution.save()

        AgentAction.objects.update_or_create(
            agent=agent,
            event=event,
            defaults={
                "project_id": event.project_id,
                "trace_id": event.trace_id,
                "span_id": execution.span_id,
                "action_type": "EXECUTE_EVENT",
                "status": execution_status,
                "summary": f"{agent.display_name}: {execution.reason_code}.",
                "metadata": {"event_id": event.event_id, "agent_version": execution.agent_version, "output": execution.output},
            },
        )
        AgentDecision.objects.update_or_create(
            event=event,
            defaults={
                "agent": decision_agent,
                "project_id": event.project_id,
                "trace_id": event.trace_id,
                "decision": state["decision"],
                "reason_code": state["reason_code"],
                "reason": state["reason"],
                "policy_version": str(result.get("output", {}).get("policy_version") or event.payload.get("policy_version", ""))[:40],
                "decided_by": (event.producer_id or "UNAUTHENTICATED_LOCAL_SOURCE") if event.event_type == "POLICY_DECIDED" else ("dev4-risk-policy-agent" if event.event_type == "POLICY_EVALUATION_REQUESTED" else "dev4-policy-gate"),
            },
        )
        execution.status = execution_status
        execution.finished_at = timezone.now()
        execution.save(update_fields=("status", "finished_at", "agent_version", "idempotency_key", "reason_code", "source_refs", "input_sha256", "output"))
        event.status = event_status
        event.save(update_fields=("status",))
        agent.last_activity_at = now
        # Business BLOCK/HUMAN_REVIEW applies to this event, not to agent health.
        agent.status = Agent.Status.IDLE
        agent.last_error_code = ""
        agent.save(update_fields=("last_activity_at", "last_error_code", "status", "updated_at"))

        AuditLog.objects.create(
            event=event,
            project_id=event.project_id,
            trace_id=event.trace_id,
            span_id=execution.span_id,
            actor_type="AGENT",
            actor_id=agent.key,
            event_type=event.event_type,
            action="AGENT_EXECUTION_FINISHED",
            status=execution_status,
            decision=state["decision"],
            details={"reason_code": execution.reason_code, "agent_version": execution.agent_version, "input_sha256": execution.input_sha256},
        )

        alert_info = ALERT_EVENT_TYPES.get(event.event_type)
        if alert_info:
            severity, title = alert_info
            AgentAlert.objects.get_or_create(
                alert_type=event.event_type,
                project_id=event.project_id,
                trace_id=event.trace_id,
                defaults={"severity": severity, "title": title, "details": {"event_id": event.event_id, "source": event.source}},
            )
        if event.event_type == "POLICY_EVALUATION_REQUESTED" and state["decision"] in {"BLOCK", "HUMAN_REVIEW"}:
            alert_type = "POLICY_BLOCKED" if state["decision"] == "BLOCK" else "POLICY_HUMAN_REVIEW"
            AgentAlert.objects.get_or_create(
                alert_type=alert_type,
                project_id=event.project_id,
                trace_id=event.trace_id,
                defaults={
                    "severity": AgentAlert.Severity.HIGH if state["decision"] == "BLOCK" else AgentAlert.Severity.WARNING,
                    "title": "Policy decision blocked" if state["decision"] == "BLOCK" else "Policy decision requires human review",
                    "details": {"event_id": event.event_id, "reason_code": state["reason_code"]},
                },
            )

        # Project-domain read models are projections of persisted agent outputs.
        # They are idempotent and retain source/event provenance.
        _project_domain_projection(event, result)

    return {"result_status": event_status, "agent_key": agent.key, "decision": state["decision"], "agent_result": result}


def _project_domain_projection(event, result):
    from datetime import date
    from .models import EvidenceSubmission, ProjectAgreement, ProjectMilestone, ProjectReference

    project = ProjectReference.objects.filter(external_id=event.project_id).first()
    if project is None:
        return
    output = result.get("output", {})
    if event.event_type == "ENGAGEMENT_CREATED" and result.get("agent_key") == "planner":
        source = event.source if event.source in ProjectReference.Provenance.values else ProjectReference.Provenance.MANUAL
        for index, row in enumerate(output.get("milestones", [])):
            target_date = date.fromisoformat(row["target_date"]) if row.get("target_date") else None
            ProjectMilestone.objects.update_or_create(
                project=project, milestone_id=row["milestone_id"],
                defaults={"title": row["title"], "order": index, "planned_work_units": row.get("work_units"),
                          "estimated_hours": row.get("estimated_hours"), "target_date": target_date,
                          "status": ProjectMilestone.Status.PROPOSED, "provenance": source,
                          "source_event_id": event.event_id, "completed_work_units": None,
                          "is_demo_only": project.is_demo_only or source == ProjectReference.Provenance.TEST_ONLY},
            )
        ProjectAgreement.objects.filter(project=project).update(plan_status=output.get("plan_status", "UNKNOWN"))
    elif event.event_type in {"EVIDENCE_REVIEW_REQUESTED", "EVIDENCE_SUBMITTED", "EVIDENCE_VERIFIED"}:
        evidence_id = output.get("evidence_id") or event.payload.get("evidence_id")
        if not evidence_id:
            return
        source_label = output.get("source", event.source)
        source = "GITHUB_API" if source_label == "GITHUB_API" else "TEST_ONLY" if source_label == "LOCAL_TEST_ONLY" else "MANUAL"
        status_label = output.get("verdict", "UNKNOWN")
        milestone = ProjectMilestone.objects.filter(project=project, milestone_id=event.milestone_id).first() if event.milestone_id else None
        EvidenceSubmission.objects.update_or_create(
            project=project, evidence_id=evidence_id,
            defaults={"milestone": milestone, "source": source, "status": status_label if status_label in EvidenceSubmission.Status.values else "UNKNOWN",
                      "repository": output.get("repository") or "", "score": output.get("score"),
                      "proof_hash": output.get("proof_hash") or "", "reasons": output.get("reasons", []),
                      "source_refs": output.get("source_refs", []), "source_event_id": event.event_id,
                      "is_demo_only": project.is_demo_only or source == "TEST_ONLY"},
        )


def build_event_workflow():
    """Compile the deterministic LangGraph route → policy → persist graph."""
    builder = StateGraph(WorkflowState)
    builder.add_node("resolve_agent", _resolve_agent)
    builder.add_node("execute_agent", _execute_agent)
    builder.add_node("apply_policy", _apply_policy)
    builder.add_node("persist_outcome", _persist_outcome)
    builder.add_edge(START, "resolve_agent")
    builder.add_edge("resolve_agent", "execute_agent")
    builder.add_edge("execute_agent", "apply_policy")
    builder.add_edge("apply_policy", "persist_outcome")
    builder.add_edge("persist_outcome", END)
    return builder.compile()


event_workflow = build_event_workflow()


def process_event(event_id: str):
    return event_workflow.invoke({"event_id": event_id})
