"""Versioned, deterministic contracts for the four autonomous Dev 4 agents.

This module consumes only events accepted by Dev 4. It does not call upstream
mini-projects and never derives an authoritative score or blockchain result.
"""

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import hashlib
import json

from django.conf import settings

from .models import SystemEvent
from .adapters.evidence import get_evidence_adapter


AGENT_CONTRACT_VERSION = "dev4-agent/1.1"
AGENT_VERSIONS = {
    "planner": "planner/1.1-local",
    "evidence": "evidence/1.1",
    "risk": "risk-policy/1.1-local",
    "settlement": "settlement-monitor/1.1-local",
}
PLANNER_MILESTONES = (
    ("analysis", "Analyse", 10),
    ("backend", "Backend", 30),
    ("frontend", "Frontend", 30),
    ("tests", "Tests & validation", 15),
    ("deployment", "Déploiement", 15),
)
EVIDENCE_COMPONENT_POINTS = {"commit": 25, "merged_pull_request": 25, "independent_approval": 25, "ci_success": 25}
POLICY_RULE_VERSION = "dev4-policy-local/1.1"


@dataclass(frozen=True)
class AgentResult:
    agent_key: str
    agent_version: str
    status: str
    reason_code: str
    output: dict
    source_refs: tuple[str, ...]

    def as_dict(self):
        result = asdict(self)
        result["source_refs"] = list(self.source_refs)
        return result


def canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _weighted_integer(total, weights):
    """Allocate exact integer totals using largest remainders, deterministically."""
    denominator = sum(weights)
    floors = [total * weight // denominator for weight in weights]
    remainder = total - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-(total * weights[i] % denominator), i))
    for index in order[:remainder]:
        floors[index] += 1
    return floors


def _planner_output(payload, event):
    if event.event_type != "ENGAGEMENT_CREATED":
        return {
            "event_type": event.event_type,
            "work_id": payload.get("work_id") or payload.get("work_unit_id") or event.milestone_id,
            "title": payload.get("title"),
            "progress": None,
            "deadline": payload.get("deadline"),
            "deadline_status": "DELAYED_REQUIRES_REVIEW" if event.event_type == "MILESTONE_DELAYED" else "SOURCE_REPORTED" if payload.get("deadline") else "UNKNOWN",
            "requires_human_review": event.event_type == "MILESTONE_DELAYED",
            "unknown_fields": ["progress"] if payload.get("progress") is None else [],
            "plan_status": "OBSERVATION_ONLY",
        }

    weights = [row[2] for row in PLANNER_MILESTONES]
    total_units = int(payload["total_work_units"])
    total_hours = int(payload["total_hours"])
    units = _weighted_integer(total_units, weights)
    hours = _weighted_integer(total_hours, weights)
    start = payload.get("start_date")
    deadline = payload.get("target_deadline")
    if isinstance(start, str):
        start = date.fromisoformat(start)
    if isinstance(deadline, str):
        deadline = date.fromisoformat(deadline)
    milestones = []
    past_due_milestones = []
    elapsed_units = 0
    span_days = (deadline - start).days if start and deadline else None
    for index, (key, title, weight) in enumerate(PLANNER_MILESTONES):
        elapsed_units += units[index]
        due_date = (start + timedelta(days=(span_days * elapsed_units // total_units))) if span_days is not None else None
        date_status = "PAST_TARGET_DATE_REQUIRES_REVIEW" if due_date and due_date < event.occurred_at.date() else "SCHEDULED" if due_date else "UNKNOWN"
        if date_status == "PAST_TARGET_DATE_REQUIRES_REVIEW":
            past_due_milestones.append(f"{payload['agreement_id']}-{key}")
        milestones.append({
            "milestone_id": f"{payload['agreement_id']}-{key}",
            "title": title,
            "weight_percent": weight,
            "work_units": units[index],
            "estimated_hours": hours[index],
            "target_date": due_date.isoformat() if due_date else None,
            "deadline_status": date_status,
            "progress_status": "UNKNOWN_NO_COMPLETION_ROLLUP",
            "status": "PROPOSED",
        })
    return {
        "agreement_id": payload["agreement_id"],
        "title": payload["title"],
        "plan_status": "PROPOSED_REQUIRES_HUMAN_APPROVAL",
        "total_work_units": total_units,
        "total_hours": total_hours,
        "milestones": milestones,
        "allocated_work_units": sum(row["work_units"] for row in milestones),
        "allocated_hours": sum(row["estimated_hours"] for row in milestones),
        "dates_calculated": bool(start and deadline),
        "deadline": deadline.isoformat() if deadline else None,
        "deadline_status": "PAST_DEADLINE_REQUIRES_REVIEW" if deadline and deadline < event.occurred_at.date() else "SCHEDULED" if deadline else "UNKNOWN",
        "past_due_milestones_at_event_time": past_due_milestones,
        "progress_status": "UNKNOWN_NO_COMPLETION_ROLLUP",
        "planning_rule_version": "planner-weighted/1.0",
        "source_event_id": event.event_id,
    }


def _evidence_output(payload, event):
    source_mode = "github" if payload.get("repository") else getattr(settings, "FW_MODE_EVIDENCE", "local")
    evidence = get_evidence_adapter(source_mode).fetch(payload)
    contributor = str(payload.get("contributor_login") or payload.get("contributor_id") or "").casefold()
    commits = evidence["commits"]
    prs = evidence["pull_requests"]
    reviews = evidence["reviews"]
    commit_ok = bool(contributor and commits) and all(contributor in {
        str(row.get("author_id", "")).casefold(), str(row.get("committer_id", "")).casefold()
    } for row in commits)
    pr_commit_shas = {str(sha).casefold() for row in prs for sha in row.get("commit_shas", [])}
    commit_linked = commit_ok and all(str(row.get("sha", "")).casefold() in pr_commit_shas for row in commits)
    matching_prs = [row for row in prs if str(row.get("author_id", "")).casefold() == contributor]
    merged_pr = bool(matching_prs) and len(matching_prs) == len(prs) and all(row.get("state") == "MERGED" for row in matching_prs)

    latest_by_reviewer = {}
    for review in reviews:
        reviewer = str(review.get("reviewer_id", "")).casefold()
        if not reviewer or reviewer == contributor:
            continue
        key = (int(review.get("pull_request_number", 0)), reviewer)
        prior = latest_by_reviewer.get(key)
        if prior is None or str(review.get("submitted_at", "")) >= str(prior.get("submitted_at", "")):
            latest_by_reviewer[key] = review
    latest_states_by_pr = {
        int(pr.get("number", 0)): [
            str(row.get("state", "")).upper()
            for (pr_number, _reviewer), row in latest_by_reviewer.items()
            if pr_number == int(pr.get("number", 0))
        ]
        for pr in prs
    }
    independent_approval = bool(prs) and all(
        "APPROVED" in states and "CHANGES_REQUESTED" not in states
        for states in latest_states_by_pr.values()
    )
    latest_states = [state for states in latest_states_by_pr.values() for state in states]
    changes_requested = "CHANGES_REQUESTED" in latest_states
    ci_status = str(evidence.get("ci_status", "PENDING")).upper()
    checks = {
        "commit_authored_by_contributor_and_linked_to_pr": commit_linked,
        "merged_pull_request_by_contributor": merged_pr,
        "independent_review_approved": independent_approval,
        "ci_success": ci_status == "SUCCESS",
    }
    points = sum(EVIDENCE_COMPONENT_POINTS[key] for key, passed in zip(EVIDENCE_COMPONENT_POINTS, checks.values()) if passed)
    hard_failures = []
    if commits and not commit_ok:
        hard_failures.append("NO_COMMIT_BY_CONTRIBUTOR")
    elif commit_ok and not commit_linked:
        hard_failures.append("COMMIT_NOT_LINKED_TO_REFERENCED_PULL_REQUEST")
    if prs and len(matching_prs) != len(prs):
        hard_failures.append("PULL_REQUEST_AUTHOR_MISMATCH")
    if matching_prs and any(row.get("state") != "MERGED" for row in matching_prs):
        hard_failures.append("PULL_REQUEST_NOT_MERGED")
    if changes_requested:
        hard_failures.append("LATEST_REVIEW_CHANGES_REQUESTED")
    if ci_status == "FAILURE":
        hard_failures.append("CI_FAILED")
    all_present = bool(commits and prs and reviews and ci_status != "PENDING")
    if hard_failures:
        verdict = "REJECTED"
    elif all(checks.values()) and all_present:
        verdict = "VERIFIED"
    else:
        verdict = "UNKNOWN"
    if verdict == "VERIFIED" and evidence["source"] == "GITHUB_API" and payload.get("contributor_identity_verified") is False:
        verdict = "UNKNOWN"
    proof_material = {
        "rule_version": "github-evidence/1.1",
        "source": evidence["source"],
        "repository": evidence.get("repository"),
        "evidence_id": payload["evidence_id"],
        "work_id": payload["work_id"],
        "contributor": contributor,
        "commits": commits,
        "pull_requests": prs,
        "reviews": reviews,
        "ci_status": ci_status,
    }
    reasons = hard_failures or [f"{key.upper()}_{'PASS' if value else 'NOT_CONFIRMED'}" for key, value in checks.items()]
    if evidence["source"] == "GITHUB_API" and payload.get("contributor_identity_verified") is False:
        reasons.insert(0, "GITHUB_IDENTITY_NOT_OAUTH_VERIFIED")
    return {
        "evidence_id": payload["evidence_id"],
        "work_id": payload["work_id"],
        "repository": evidence.get("repository"),
        "source": evidence["source"],
        "verdict": verdict,
        "score": points,
        "score_type": "LOCAL_RULE_SCORE_NOT_OFFICIAL_DEV2_SCORE",
        "checks": checks,
        "reasons": reasons,
        "proof_hash": canonical_hash(proof_material),
        "proof_hash_scope": "HASH_OF_FETCHED_EVIDENCE_AND_RULE_VERSION_NOT_ON_CHAIN",
        "source_refs": evidence.get("source_refs", []),
        "rule_version": "github-evidence/1.1",
        "hard_failures": hard_failures,
        "synthetic_data": evidence["source"] == "LOCAL_TEST_ONLY",
        "contributor_identity_verified": payload.get("contributor_identity_verified") is True,
    }


def _risk_output(payload, event):
    from .models import AgentExecution, SettlementRecord, SystemEvent

    evidence_event = SystemEvent.objects.filter(event_id=payload["evidence_event_id"]).first()
    execution = None
    same_correlation = bool(event.correlation_id) and evidence_event is not None and evidence_event.correlation_id == event.correlation_id
    if evidence_event and same_correlation and evidence_event.project_id == event.project_id and evidence_event.event_type == "EVIDENCE_REVIEW_REQUESTED":
        execution = AgentExecution.objects.filter(agent__key="evidence", event=evidence_event).first()
    evidence_output = execution.output if execution and execution.status in {AgentExecution.Status.COMPLETED, AgentExecution.Status.BLOCKED} else {}
    planner_event = SystemEvent.objects.filter(event_id=payload["planner_event_id"]).first()
    planner_execution = None
    if (
        planner_event
        and event.correlation_id
        and planner_event.project_id == event.project_id
        and planner_event.correlation_id == event.correlation_id
        and planner_event.event_type == "ENGAGEMENT_CREATED"
    ):
        planner_execution = AgentExecution.objects.filter(agent__key="planner", event=planner_event, status=AgentExecution.Status.COMPLETED).first()
    planner_output = planner_execution.output if planner_execution else {}
    planned_milestone = any(row.get("milestone_id") == payload["milestone_id"] for row in planner_output.get("milestones", []))
    verdict = evidence_output.get("verdict", "UNKNOWN")
    score = evidence_output.get("score")
    reported_risk = payload["risk_level"]
    risk_components = []
    evidence_points = {"VERIFIED": 0, "UNKNOWN": 25, "REJECTED": 60}.get(verdict, 25)
    risk_components.append({"factor": "EVIDENCE_" + verdict, "points": evidence_points})
    for key, label, penalty in (
        ("milestone_complete", "MILESTONE", 20),
        ("client_approved", "CLIENT_APPROVAL", 30),
        ("conditions_met", "CONTRACT_CONDITIONS", 40),
    ):
        value = payload[key]
        risk_components.append({"factor": label + ("_PASS" if value is True else "_FAIL" if value is False else "_UNKNOWN"), "points": 0 if value is True else penalty if value is False else 10})
    reported_risk_points = {"LOW": 0, "MEDIUM": 20, "HIGH": 40, "UNKNOWN": 10}[reported_risk]
    risk_components.append({"factor": "REPORTED_RISK_" + reported_risk, "points": reported_risk_points})
    risk_score = min(100, sum(row["points"] for row in risk_components))
    calculated_risk = "HIGH" if reported_risk == "HIGH" or risk_score >= 50 else "MEDIUM" if risk_score >= 20 else "LOW"
    settlement = None
    settlement_id = payload.get("settlement_id")
    if settlement_id:
        settlement = SettlementRecord.objects.filter(settlement_id=settlement_id).first()
    settlement_valid = not settlement_id or bool(
        settlement
        and settlement.project_id == event.project_id
        and settlement.status in {SettlementRecord.Status.REQUESTED, SettlementRecord.Status.POLICY_PENDING}
    )
    reasons = []
    decision = "HUMAN_REVIEW"
    if not settlement_valid:
        decision, reasons = "BLOCK", ["SETTLEMENT_NOT_FOUND_PROJECT_MISMATCH_OR_INVALID_STATE"]
    elif planner_output and not planned_milestone:
        decision, reasons = "BLOCK", ["MILESTONE_NOT_IN_PLANNER_OUTPUT"]
    elif payload["milestone_complete"] is False:
        decision, reasons = "BLOCK", ["MILESTONE_NOT_COMPLETE"]
    elif payload["client_approved"] is False:
        decision, reasons = "BLOCK", ["CLIENT_APPROVAL_DENIED"]
    elif payload["conditions_met"] is False:
        decision, reasons = "BLOCK", ["CONTRACT_CONDITION_FAILED"]
    elif reported_risk == "HIGH":
        decision, reasons = "BLOCK", ["RISK_LEVEL_HIGH"]
    elif not planner_output:
        reasons.append("PLANNER_EXECUTION_MISSING_OR_NOT_CORRELATED")
    elif not planned_milestone:
        reasons.append("MILESTONE_NOT_CONFIRMED_IN_PLANNER_OUTPUT")
    elif not evidence_output:
        reasons.append("EVIDENCE_EXECUTION_MISSING_OR_NOT_COMPLETED")
    elif evidence_output.get("work_id") != payload["milestone_id"]:
        decision, reasons = "BLOCK", ["EVIDENCE_WORK_MILESTONE_MISMATCH"]
    elif verdict == "REJECTED":
        decision, reasons = "BLOCK", ["EVIDENCE_REJECTED"] + evidence_output.get("reasons", [])
    elif calculated_risk == "HIGH":
        decision, reasons = "BLOCK", ["CALCULATED_RISK_HIGH"]
    elif reported_risk == "UNKNOWN":
        reasons.append("RISK_LEVEL_UNKNOWN")
    elif verdict != "VERIFIED":
        reasons.append("EVIDENCE_NOT_VERIFIED")
    elif payload["milestone_complete"] is None or payload["client_approved"] is None or payload["conditions_met"] is None:
        reasons.append("REQUIRED_POLICY_FACT_UNKNOWN")
    elif calculated_risk != "LOW":
        reasons.append("RISK_REQUIRES_HUMAN_REVIEW")
    elif score is None or score < 100:
        reasons.append("EVIDENCE_SCORE_BELOW_LOCAL_RELEASE_THRESHOLD")
    else:
        decision, reasons = "ALLOW", ["ALL_LOCAL_POLICY_GATES_PASSED"]
    if decision == "HUMAN_REVIEW" and not reasons:
        reasons = ["POLICY_REVIEW_REQUIRED"]
    source_refs = list(evidence_output.get("source_refs", []))
    source_refs.extend([payload["planner_event_id"], payload["evidence_event_id"], event.event_id])
    output = {
        "evaluation_id": payload["evaluation_id"],
        "decision": decision,
        "reason_codes": reasons,
        "policy_version": POLICY_RULE_VERSION,
        "decision_scope": "LOCAL_SIMULATION_NO_TRANSFER",
        "planner_event_id": payload["planner_event_id"],
        "planned_milestone_verified": planned_milestone,
        "evidence_event_id": payload["evidence_event_id"],
        "evidence_verdict": verdict,
        "evidence_score": score,
        "evidence_score_source": evidence_output.get("score_type"),
        "reported_risk_level": reported_risk,
        "calculated_risk_level": calculated_risk,
        "risk_score": risk_score,
        "risk_components": risk_components,
        "settlement_id": payload.get("settlement_id"),
        "settlement_status_at_evaluation": settlement.status if settlement else None,
        "source_refs": list(dict.fromkeys(source_refs)),
    }
    return output


def execute_agent(agent_key: str, event: SystemEvent) -> AgentResult:
    """Return a typed observation; unknown business facts stay explicitly unknown."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    base = {
        "agent_key": agent_key,
        "agent_version": AGENT_VERSIONS.get(agent_key, AGENT_CONTRACT_VERSION),
        "status": "SUCCEEDED",
        "reason_code": "SOURCE_EVENT_RECORDED",
        "source_refs": (event.event_id,),
    }

    if agent_key == "planner":
        if event.event_type == "ENGAGEMENT_CREATED":
            return AgentResult(**base, output=_planner_output(payload, event))
        output = {
            "event_type": event.event_type,
            "work_id": payload.get("work_id") or payload.get("work_unit_id") or event.milestone_id or None,
            "title": payload.get("title") or None,
            "progress": None,
            "deadline": payload.get("deadline") or None,
            "unknown_fields": [key for key, value in (("progress", payload.get("progress")), ("deadline", payload.get("deadline"))) if value is None],
        }
        if output["work_id"] is None:
            base.update(status="BLOCKED", reason_code="WORK_REFERENCE_MISSING")
        return AgentResult(**base, output=output)

    if agent_key == "evidence":
        if event.event_type == "EVIDENCE_REVIEW_REQUESTED":
            output = _evidence_output(payload, event)
            base["reason_code"] = output["verdict"]
            base["source_refs"] = tuple(output["source_refs"] or [event.event_id])
            if output["verdict"] == "REJECTED":
                base["status"] = "BLOCKED"
            return AgentResult(**base, output=output)
        if event.event_type == "EVIDENCE_VERIFIED":
            verdict = "SOURCE_REPORTED_VERIFIED"
            reason_code = "VERIFICATION_EVENT_OBSERVED"
        elif event.event_type == "EVIDENCE_MISSING":
            verdict = "REJECTED"
            reason_code = "SOURCE_REPORTED_MISSING"
        elif event.event_type == "EVIDENCE_SUBMITTED":
            # Presence of a digest is integrity metadata, not proof of truth.
            verdict = "UNKNOWN"
            reason_code = "OWNER_VERIFICATION_NOT_RECEIVED"
        else:
            verdict = "UNKNOWN"
            reason_code = "EVIDENCE_STATUS_NOT_PROVIDED"
        base["reason_code"] = reason_code
        return AgentResult(**base, output={
            "evidence_id": payload.get("evidence_id"),
            "work_id": payload.get("work_id"),
            "verdict": verdict,
            "content_sha256": payload.get("content_sha256"),
        })

    if agent_key == "risk":
        if event.event_type == "POLICY_EVALUATION_REQUESTED":
            output = _risk_output(payload, event)
            base["reason_code"] = output["reason_codes"][0]
            base["status"] = "BLOCKED" if output["decision"] in {"BLOCK", "HUMAN_REVIEW"} else "SUCCEEDED"
            base["source_refs"] = tuple(output["source_refs"])
            return AgentResult(**base, output=output)
        if event.event_type == "POLICY_DECIDED":
            decision = payload.get("decision")
            status = "SUCCEEDED" if decision in {"ALLOW", "BLOCK", "HUMAN_REVIEW"} else "BLOCKED"
            reason_code = payload.get("reason_code") or "POLICY_REASON_MISSING"
            output = {
                "decision": decision if status == "SUCCEEDED" else "HUMAN_REVIEW",
                "policy_version": payload.get("policy_version"),
                "score": None,
                "score_source": None,
                "reason_code": reason_code,
            }
            return AgentResult(agent_key, AGENT_CONTRACT_VERSION, status, reason_code, output, base["source_refs"])
        base["reason_code"] = "AUTHORITATIVE_POLICY_NOT_RECEIVED"
        return AgentResult(**base, output={
            "decision": "HUMAN_REVIEW" if event.event_type == "HIGH_RISK" else "PENDING",
            "score": None,
            "score_source": None,
            "policy_version": None,
        })

    if agent_key == "settlement":
        settlement_id = payload.get("settlement_id")
        if not settlement_id:
            base.update(status="BLOCKED", reason_code="SETTLEMENT_REFERENCE_MISSING")
        return AgentResult(**base, output={
            "settlement_id": settlement_id,
            "reported_status": payload.get("status"),
            "transaction_id": payload.get("transaction_id") or None,
            "signature_or_transfer_performed": False,
        })

    return AgentResult("", AGENT_CONTRACT_VERSION, "PERMANENT_FAILURE", "UNKNOWN_AGENT", {}, ())
