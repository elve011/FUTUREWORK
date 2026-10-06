import hashlib
import uuid
from decimal import Decimal, InvalidOperation
from importlib.util import find_spec

from django.conf import settings
import hmac
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .adapters.mock import get_hedera_adapter, get_project_adapter
from .adapters.hedera import HederaObserverUnavailable
from .mock_data import ensure_mock_agents
from .models import (
    Agent,
    AgentAction,
    AgentAlert,
    AgentDecision,
    AgentExecution,
    AuditLog,
    DashboardMetric,
    EventOutbox,
    EvidenceSubmission,
    FreelancerProfile,
    ProjectAuditLog,
    ProjectImportBatch,
    ProjectReference,
    ProjectAgreement,
    ProjectApproval,
    ProjectMember,
    ProjectMilestone,
    SettlementRecord,
    SystemEvent,
)
from .hedera_payment import (
    DEMO_PAYMENT_HBAR,
    HederaPaymentConfigurationError,
    HederaPaymentSubmissionError,
    submit_testnet_hbar_transfer,
    validate_testnet_payment_config,
)
from .security import canonical_payload_hash, redact_sensitive
from .serializers import AgentSerializer, IngestEventSerializer, ProjectInputSerializer, ProjectReferenceSerializer
from .project_registry import extract_import_rows, validate_import_rows


@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "service": "futurework-dev4", "time": timezone.now()})


@api_view(["GET"])
def agents(request):
    ensure_mock_agents()
    rows = AgentSerializer(Agent.objects.all(), many=True).data
    return Response({"count": len(rows), "results": rows, "source": "agent-registry"})


@api_view(["GET"])
def agent_status(request):
    ensure_mock_agents()
    rows = AgentSerializer(Agent.objects.all(), many=True).data
    return Response({"count": len(rows), "results": rows, "source": "agent-registry"})


@api_view(["GET"])
def agent_actions(request):
    queryset = AgentAction.objects.select_related("agent", "event").all()
    agent_key = request.query_params.get("agent")
    project_id = request.query_params.get("project_id")
    if not _operator_id(request):
        if not project_id:
            return Response({"error": "PROJECT_SCOPE_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)
        denied = _project_access_error(request, project_id)
        if denied:
            return denied
    if agent_key:
        queryset = queryset.filter(agent__key=agent_key)
    if project_id:
        queryset = queryset.filter(project_id=project_id)
    results = [
        {
            "id": row.id,
            "agent_id": row.agent.key,
            "project_id": row.project_id,
            "event_id": row.event.event_id,
            "trace_id": row.trace_id,
            "action_type": row.action_type,
            "status": row.status,
            "summary": row.summary,
            "metadata": row.metadata,
            "created_at": row.created_at,
        }
        for row in queryset[:200]
    ]
    return Response({"count": len(results), "results": results})


@api_view(["GET"])
def agent_history(request, agent_id):
    ensure_mock_agents()
    project_id = request.query_params.get("project_id")
    if not _operator_id(request):
        if not project_id:
            return Response({"error": "PROJECT_SCOPE_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)
        denied = _project_access_error(request, project_id)
        if denied:
            return denied
    agent = get_object_or_404(Agent, key=agent_id)
    timeline = []
    actions = AgentAction.objects.filter(agent=agent)
    decisions = AgentDecision.objects.filter(agent=agent)
    executions = AgentExecution.objects.filter(agent=agent)
    if project_id:
        actions = actions.filter(project_id=project_id)
        decisions = decisions.filter(project_id=project_id)
        executions = executions.filter(event__project_id=project_id)
    for row in actions.select_related("event")[:100]:
        timeline.append({"kind": "ACTION", "at": row.created_at, "trace_id": row.trace_id, "correlation_id": row.event.correlation_id, "event_id": row.event.event_id, "status": row.status, "summary": row.summary, "metadata": row.metadata})
    for row in decisions.select_related("event")[:100]:
        timeline.append({"kind": "DECISION", "at": row.created_at, "trace_id": row.trace_id, "correlation_id": row.event.correlation_id, "event_id": row.event.event_id, "status": row.decision, "summary": row.reason})
    for row in executions.select_related("event")[:100]:
        duration_ms = None
        if row.started_at and row.finished_at:
            duration_ms = max(0, round((row.finished_at - row.started_at).total_seconds() * 1000))
        timeline.append({"kind": "EXECUTION", "at": row.created_at, "trace_id": row.trace_id, "correlation_id": row.event.correlation_id, "event_id": row.event.event_id, "status": row.status, "summary": row.error_code or row.reason_code or row.status, "agent_version": row.agent_version, "reason_code": row.reason_code, "source_refs": row.source_refs, "input_sha256": row.input_sha256, "output": row.output, "duration_ms": duration_ms})
    timeline.sort(key=lambda item: item["at"], reverse=True)
    return Response({"agent": agent.key, "count": len(timeline), "results": timeline[:200]})


@api_view(["GET"])
def settlements(request):
    queryset = SettlementRecord.objects.all()
    project_id = request.query_params.get("project_id")
    if not _operator_id(request):
        if not getattr(request.user, "is_authenticated", False):
            return Response({"error": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)
        if not project_id:
            return Response({"error": "PROJECT_SCOPE_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)
        denied = _project_access_error(request, project_id)
        if denied:
            return denied
    settlement_status = request.query_params.get("status")
    if project_id:
        queryset = queryset.filter(project_id=project_id)
    if settlement_status:
        if settlement_status not in SettlementRecord.Status.values:
            return Response({"error": "INVALID_SETTLEMENT_STATUS"}, status=400)
        queryset = queryset.filter(status=settlement_status)
    total = queryset.count()
    try:
        limit = min(100, max(1, int(request.query_params.get("limit", "50"))))
        offset = max(0, int(request.query_params.get("offset", "0")))
    except ValueError:
        return Response({"error": "INVALID_PAGINATION"}, status=400)
    results = [
        {
            "settlement_id": row.settlement_id,
            "project_id": row.project_id,
            "trace_id": row.trace_id,
            "status": row.status,
            "transaction_id": row.transaction_id or None,
            "consensus_timestamp": row.consensus_timestamp or None,
            "network": row.network or None,
            "source": row.source or None,
            "last_observed_at": row.last_observed_at,
            "last_checked_at": row.last_checked_at,
            "last_error_code": row.last_error_code or None,
            "updated_at": row.updated_at,
        }
        for row in queryset.order_by("-updated_at", "settlement_id")[offset:offset + limit]
    ]
    return Response({"count": total, "limit": limit, "offset": offset, "results": results})


@api_view(["GET"])
def settlement_detail(request, settlement_id):
    row = get_object_or_404(SettlementRecord, settlement_id=settlement_id)
    if not _operator_id(request):
        denied = _project_access_error(request, row.project_id)
        if denied:
            return denied
    return Response({
        "settlement_id": row.settlement_id,
        "project_id": row.project_id,
        "trace_id": row.trace_id,
        "status": row.status,
        "transaction_id": row.transaction_id or None,
        "consensus_timestamp": row.consensus_timestamp or None,
        "network": row.network or None,
        "source": row.source or None,
        "last_observed_at": row.last_observed_at,
        "last_checked_at": row.last_checked_at,
        "last_error_code": row.last_error_code or None,
        "transitions": [
            {"from_status": item.from_status or None, "to_status": item.to_status, "source": item.source, "transaction_id": item.transaction_id or None, "consensus_timestamp": item.consensus_timestamp or None, "reason_code": item.reason_code, "observed_at": item.observed_at, "event_id": item.event.event_id}
            for item in row.transitions.select_related("event").all()
        ],
        "monitor_attempts": [
            {"outcome": item.outcome, "source": item.source, "error_code": item.error_code or None, "observed_status": item.observed_status or None, "transaction_id": item.transaction_id or None, "checked_at": item.checked_at}
            for item in row.monitor_attempts.all()[:50]
        ],
    })


def _project_adapter_or_response():
    try:
        return get_project_adapter(settings.FW_MODE_PROJECT), None
    except NotImplementedError as exc:
        return None, Response({"error": "SOURCE_MODE_UNAVAILABLE", "source": "project", "detail": str(exc)}, status=503)


def _hedera_adapter_or_response():
    try:
        return get_hedera_adapter(settings.FW_MODE_HEDERA), None
    except NotImplementedError as exc:
        return None, Response({"error": "SOURCE_MODE_UNAVAILABLE", "source": "hedera", "detail": str(exc)}, status=503)
    except HederaObserverUnavailable as exc:
        return None, Response(
            {"error": "HEDERA_SOURCE_UNAVAILABLE", "source_status": "UNAVAILABLE", "detail": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def _project_snapshot_or_response(project_id):
    local_project = ProjectReference.objects.filter(external_id=project_id).first()
    if local_project:
        return _local_project_snapshot(local_project), None
    adapter, error_response = _project_adapter_or_response()
    if error_response:
        return None, error_response
    try:
        return adapter.get_project_snapshot(project_id), None
    except KeyError:
        return None, Response({"error": "PROJECT_NOT_FOUND", "project_id": project_id}, status=404)


def _local_project_snapshot(project):
    agreement = getattr(project, "agreement", None)
    milestones = list(project.milestones.all())
    evidence_rows = list(project.evidence_submissions.all())
    project_settlements = list(SettlementRecord.objects.filter(project_id=project.external_id))
    latest_risk = AgentExecution.objects.filter(agent__key="risk", event__project_id=project.external_id).exclude(output={}).order_by("-finished_at").first()
    risk_decisions = AgentDecision.objects.filter(project_id=project.external_id, decision__in=("BLOCK", "HUMAN_REVIEW"))
    completed_milestones = sum(row.status == ProjectMilestone.Status.COMPLETED for row in milestones)
    planned_units = [row.planned_work_units for row in milestones]
    completed_units = [row.completed_work_units for row in milestones]
    total_units = sum(planned_units) if planned_units and all(value is not None for value in planned_units) else agreement.total_work_units if agreement else None
    done_units = sum(completed_units) if completed_units and all(value is not None for value in completed_units) else None
    progress = round(done_units * 100 / total_units, 2) if done_units is not None and total_units else None
    evidence_verified = sum(row.status == EvidenceSubmission.Status.VERIFIED for row in evidence_rows)
    return {
        "project_id": project.external_id,
        "title": project.title,
        "description": project.description,
        "status": project.status,
        "updated_at": project.updated_at,
        "source": "local-registry",
        "provenance": project.provenance,
        "metrics_status": "PERSISTED_WITH_UNKNOWN_FIELDS",
        "progress_percent": progress,
        "units": {"completed": done_units, "total": total_units},
        "milestones": {"completed": completed_milestones if milestones else None, "total": len(milestones) if milestones else None},
        "evidence": {"submitted": len(evidence_rows), "verified": evidence_verified, "missing": None},
        "risk": {"level": (latest_risk.output.get("calculated_risk_level") or "UNKNOWN") if latest_risk else "UNKNOWN",
                 "open_items": risk_decisions.count() if latest_risk else None},
        "settlements": {
            "confirmed": sum(row.status == SettlementRecord.Status.CONFIRMED for row in project_settlements),
            "pending": sum(row.status in {SettlementRecord.Status.REQUESTED, SettlementRecord.Status.POLICY_PENDING,
                                         SettlementRecord.Status.AUTHORIZED, SettlementRecord.Status.SUBMITTED_BY_OWNER,
                                         SettlementRecord.Status.OBSERVED_PENDING} for row in project_settlements),
            "failed": sum(row.status == SettlementRecord.Status.FAILED for row in project_settlements),
        },
    }


def _operator_id(request):
    operator_id = request.headers.get("X-Operator-ID", "").strip()
    presented_key = request.headers.get("X-Operator-Key", "")
    expected_key = settings.FW_OPERATOR_API_KEYS.get(operator_id, "")
    if not operator_id or not expected_key or not hmac.compare_digest(presented_key, expected_key):
        return None
    return operator_id


def _active_freelancer(request):
    profile = getattr(request.user, "freelancer_profile", None)
    return bool(
        getattr(request.user, "is_authenticated", False)
        and profile
        and profile.status == FreelancerProfile.Status.ACTIVE
        and profile.role in {FreelancerProfile.Role.FREELANCER, FreelancerProfile.Role.CLIENT}
    )


def _can_submit_project_work(request, project):
    profile = getattr(request.user, "freelancer_profile", None)
    if not profile or profile.role != FreelancerProfile.Role.FREELANCER or profile.status != FreelancerProfile.Status.ACTIVE:
        return False
    return project.owner_id == request.user.pk or ProjectMember.objects.filter(
        project=project, user=request.user, role="FREELANCER"
    ).exists()


def _project_access_error(request, project_id):
    """Hide project existence unless the owner or a configured operator asks."""
    project = ProjectReference.objects.filter(external_id=project_id).only("owner_id").first()
    if project is None:
        if _operator_id(request) or (settings.DEBUG and project_id == "FW-DEMO-001"):
            return None
        return Response({"error": "PROJECT_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
    if _operator_id(request):
        return None
    if (
        project.owner_id
        and getattr(request.user, "is_authenticated", False)
        and project.owner_id == request.user.pk
        and _active_freelancer(request)
    ):
        return None
    if (
        getattr(request.user, "is_authenticated", False)
        and _active_freelancer(request)
        and ProjectMember.objects.filter(project=project, user=request.user).exists()
    ):
        return None
    return Response({"error": "PROJECT_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)


def _enqueue_local_event(*, project_id, event_type, payload, correlation_id, milestone_id=None):
    """Validate and persist an event and its outbox row in the caller's transaction."""
    import uuid
    event_data = {
        "schema_version": "dev4-local/2.0", "producer_id": "dev4-local-ui",
        "event_id": f"dev4-{uuid.uuid4().hex}", "event_type": event_type,
        "project_id": project_id, "occurred_at": timezone.now(), "source": "MANUAL",
        "payload": payload, "correlation_id": correlation_id,
    }
    if milestone_id:
        event_data["milestone_id"] = milestone_id
    serializer = IngestEventSerializer(data=event_data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    event = SystemEvent.objects.create(
        **values, payload_sha256=canonical_payload_hash(values["payload"]),
        trace_id=f"FW-TRACE-{uuid.uuid4().hex[:16].upper()}",
    )
    AuditLog.objects.create(
        event=event, project_id=project_id, trace_id=event.trace_id,
        actor_type="USER", actor_id="local-project-workflow", event_type=event_type,
        action="LOCAL_EVENT_ENQUEUED", status=event.status,
        details={"source": "MANUAL", "schema_version": event.schema_version},
    )
    EventOutbox.objects.create(event=event)
    return event


@api_view(["GET", "POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def freelancer_projects(request):
    """Project API whose query set is always scoped to the signed-in account."""
    if not _active_freelancer(request):
        return Response({"error": "ACTIVE_FREELANCER_ACCOUNT_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)
    if request.method == "GET":
        projects = ProjectReference.objects.filter(Q(owner=request.user) | Q(members__user=request.user)).distinct().order_by("title", "external_id")
        rows = ProjectReferenceSerializer(projects, many=True).data
        return Response({"count": len(rows), "results": rows, "source": "freelancer-registry"})

    serializer = ProjectInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = dict(serializer.validated_data)
    agreement_values = {key: values.pop(key, None) for key in (
        "budget_amount", "currency", "total_hours", "total_work_units", "start_date",
        "target_deadline", "github_repository", "conditions",
    )}
    try:
        with transaction.atomic():
            project = ProjectReference.objects.create(
                **values,
                provenance=ProjectReference.Provenance.MANUAL,
                created_by=request.user.email,
                owner=request.user,
                is_demo_only=False,
            )
            agreement = ProjectAgreement.objects.create(project=project, **agreement_values)
            ProjectAuditLog.objects.create(
                project=project,
                actor_id=request.user.email,
                action="FREELANCER_PROJECT_CREATED",
                details={"owner_user_id": request.user.pk, "provenance": project.provenance},
            )
            planner_event = None
            if agreement.total_hours and agreement.total_work_units:
                planner_event = _enqueue_local_event(
                    project_id=project.external_id, event_type="ENGAGEMENT_CREATED",
                    correlation_id=f"project:{project.external_id}",
                    payload={
                        "agreement_id": project.external_id, "title": project.title,
                        "total_hours": agreement.total_hours, "total_work_units": agreement.total_work_units,
                        "start_date": agreement.start_date.isoformat() if agreement.start_date else None,
                        "target_deadline": agreement.target_deadline.isoformat() if agreement.target_deadline else None,
                    },
                )
    except IntegrityError:
        return Response({"error": "PROJECT_ID_CONFLICT", "project_id": values["external_id"]}, status=status.HTTP_409_CONFLICT)
    response = ProjectReferenceSerializer(project).data
    response.update({"agreement_id": project.external_id, "planner_event_id": planner_event.event_id if planner_event else None,
                     "plan_status": "QUEUED" if planner_event else "UNKNOWN_INSUFFICIENT_AGREEMENT_DATA"})
    return Response(response, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def freelancer_project_detail(request, project_id):
    if not _active_freelancer(request):
        return Response({"error": "ACTIVE_FREELANCER_ACCOUNT_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)
    project = get_object_or_404(ProjectReference, external_id=project_id)
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    if request.method == "PATCH":
        if project.owner_id != request.user.pk:
            return Response({"error": "PROJECT_OWNER_REQUIRED"}, status=403)
        allowed = {"title", "description", "status"}
        unknown = set(request.data) - allowed
        if unknown:
            return Response({"error": "UNKNOWN_PROJECT_FIELD", "fields": sorted(unknown)}, status=400)
        if "title" in request.data:
            title = str(request.data["title"]).strip()
            if not title or len(title) > 180:
                return Response({"error": "INVALID_TITLE"}, status=400)
            project.title = title
        if "description" in request.data:
            description = str(request.data["description"])
            if len(description) > 1000:
                return Response({"error": "INVALID_DESCRIPTION"}, status=400)
            project.description = description
        if "status" in request.data:
            project.status = str(request.data["status"])[:40]
        project.save()
        ProjectAuditLog.objects.create(project=project, actor_id=request.user.email,
                                       action="FREELANCER_PROJECT_UPDATED", details={"fields": sorted(request.data.keys())})
        return Response(ProjectReferenceSerializer(project).data)
    agreement = getattr(project, "agreement", None)
    return Response({
        **ProjectReferenceSerializer(project).data,
        "agreement": ({"budget_amount": agreement.budget_amount, "currency": agreement.currency,
                       "total_hours": agreement.total_hours, "total_work_units": agreement.total_work_units,
                       "start_date": agreement.start_date, "target_deadline": agreement.target_deadline,
                       "github_repository": agreement.github_repository, "conditions": agreement.conditions,
                       "approval_status": agreement.approval_status, "plan_status": agreement.plan_status,
                       "provenance": agreement.provenance} if agreement else None),
        "milestones": [{"milestone_id": row.milestone_id, "title": row.title, "description": row.description,
                        "order": row.order, "planned_work_units": row.planned_work_units,
                        "estimated_hours": row.estimated_hours, "completed_work_units": row.completed_work_units,
                        "target_date": row.target_date, "status": row.status, "provenance": row.provenance}
                       for row in project.milestones.all()],
        "evidence": [{"evidence_id": row.evidence_id, "milestone_id": row.milestone.milestone_id if row.milestone_id else None,
                      "source": row.source, "status": row.status,
                      "repository": row.repository or None, "score": row.score, "proof_hash": row.proof_hash or None,
                      "reasons": row.reasons, "source_refs": row.source_refs, "source_event_id": row.source_event_id}
                     for row in project.evidence_submissions.all()[:100]],
        "approvals": [{"kind": row.kind, "milestone_id": row.milestone.milestone_id if row.milestone_id else None,
                       "decision": row.decision, "reason": row.reason,
                       "actor_id": row.actor_id, "created_at": row.created_at}
                      for row in project.approvals.all()[:100]],
        "events": [{"event_id": row.event_id, "event_type": row.event_type, "status": row.status,
                    "correlation_id": row.correlation_id, "occurred_at": row.occurred_at}
                   for row in SystemEvent.objects.filter(project_id=project_id).order_by("-received_at")[:100]],
        "decisions": [{"decision": row.decision, "reason_code": row.reason_code, "reason": row.reason,
                       "policy_version": row.policy_version, "event_id": row.event.event_id, "created_at": row.created_at}
                      for row in AgentDecision.objects.filter(project_id=project_id).select_related("event").order_by("-created_at")[:100]],
    })


def _hedera_demo_project_error(request, project_id):
    profile = getattr(request.user, "freelancer_profile", None)
    if (
        not settings.DEBUG
        or not _active_freelancer(request)
        or not profile.is_demo_only
        or project_id != "HEDERA-DEMO-001"
    ):
        return Response({"error": "LOCAL_HEDERA_DEMO_ONLY"}, status=403)
    project = ProjectReference.objects.filter(
        external_id=project_id,
        owner=request.user,
        is_demo_only=True,
        provenance=ProjectReference.Provenance.TEST_ONLY,
    ).first()
    if project is None:
        return Response({"error": "HEDERA_DEMO_PROJECT_NOT_FOUND"}, status=404)
    return project


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def freelancer_hedera_demo_config(request, project_id):
    project_or_error = _hedera_demo_project_error(request, project_id)
    if isinstance(project_or_error, Response):
        return project_or_error
    try:
        validate_testnet_payment_config(
            network=settings.FW_HEDERA_NETWORK,
            operator_id=settings.FW_HEDERA_DEMO_OPERATOR_ACCOUNT_ID,
            private_key=settings.FW_HEDERA_DEMO_OPERATOR_PRIVATE_KEY,
            recipient_id=settings.FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID,
        )
        enabled = find_spec("hiero_sdk_python") is not None
        reason = None if enabled else "HEDERA_SDK_NOT_INSTALLED"
    except HederaPaymentConfigurationError as exc:
        enabled = False
        reason = str(exc)
    except ImportError:
        enabled = False
        reason = "HEDERA_SDK_NOT_INSTALLED"

    milestone_payments = {}
    for milestone in project_or_error.milestones.all():
        digest = hashlib.sha256(
            f"{project_or_error.external_id}:{milestone.milestone_id}".encode("utf-8")
        ).hexdigest()[:40]
        settlement = SettlementRecord.objects.filter(settlement_id=f"DEMO-HBAR-{digest}").first()
        if settlement is not None:
            milestone_payments[milestone.milestone_id] = {
                "status": settlement.status,
                "transaction_id": settlement.transaction_id or None,
                "last_error_code": settlement.last_error_code or None,
            }

    return Response({
        "network": "testnet",
        "operator_account_id": settings.FW_HEDERA_DEMO_OPERATOR_ACCOUNT_ID,
        "recipient_account_id": settings.FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID,
        "amount_hbar": DEMO_PAYMENT_HBAR,
        "enabled": enabled,
        "reason": reason,
        "milestone_payments": milestone_payments,
    })


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def freelancer_hedera_demo_transfer(request, project_id):
    project_or_error = _hedera_demo_project_error(request, project_id)
    if isinstance(project_or_error, Response):
        return project_or_error
    if set(request.data) != {"milestone_id", "amount_hbar", "confirm"} or request.data.get("confirm") is not True:
        return Response({"error": "HEDERA_TESTNET_TRANSFER_CONFIRMATION_REQUIRED"}, status=400)
    try:
        amount = Decimal(str(request.data["amount_hbar"]))
    except (InvalidOperation, TypeError, ValueError):
        return Response({"error": "HEDERA_TESTNET_AMOUNT_INVALID"}, status=400)
    if amount != Decimal(DEMO_PAYMENT_HBAR):
        return Response({"error": "HEDERA_TESTNET_AMOUNT_MUST_BE_0_1_HBAR"}, status=400)

    try:
        operator_key = validate_testnet_payment_config(
            network=settings.FW_HEDERA_NETWORK,
            operator_id=settings.FW_HEDERA_DEMO_OPERATOR_ACCOUNT_ID,
            private_key=settings.FW_HEDERA_DEMO_OPERATOR_PRIVATE_KEY,
            recipient_id=settings.FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID,
        )
    except HederaPaymentConfigurationError as exc:
        return Response({"error": str(exc)}, status=503)

    milestone_id = request.data["milestone_id"]
    if not isinstance(milestone_id, str) or not milestone_id.strip() or len(milestone_id) > 128:
        return Response({"error": "HEDERA_TESTNET_MILESTONE_INVALID"}, status=400)
    project = project_or_error
    settlement_digest = hashlib.sha256(f"{project.external_id}:{milestone_id}".encode("utf-8")).hexdigest()[:40]
    settlement_id = f"DEMO-HBAR-{settlement_digest}"
    trace_id = f"FW-TRACE-{uuid.uuid4().hex[:16].upper()}"

    try:
        with transaction.atomic():
            milestone = ProjectMilestone.objects.select_for_update().filter(
                project=project, milestone_id=milestone_id,
            ).first()
            if milestone is None:
                return Response({"error": "MILESTONE_NOT_FOUND"}, status=404)
            if (
                milestone.status != ProjectMilestone.Status.COMPLETED
                or milestone.planned_work_units is None
                or milestone.completed_work_units != milestone.planned_work_units
            ):
                return Response({"error": "HEDERA_MILESTONE_NOT_COMPLETED"}, status=409)
            if not EvidenceSubmission.objects.filter(
                project=project, milestone=milestone, status=EvidenceSubmission.Status.VERIFIED,
            ).exists():
                return Response({"error": "HEDERA_MILESTONE_EVIDENCE_NOT_VERIFIED"}, status=409)
            if not ProjectApproval.objects.filter(
                project=project,
                milestone=milestone,
                kind=ProjectApproval.Kind.MILESTONE,
                decision="APPROVED",
            ).exists():
                return Response({"error": "HEDERA_MILESTONE_NOT_APPROVED"}, status=409)
            settlement = SettlementRecord.objects.filter(settlement_id=settlement_id).first()
            if settlement is not None and settlement.status != SettlementRecord.Status.FAILED:
                return Response({"error": "HEDERA_MILESTONE_ALREADY_PAID"}, status=409)
            if settlement is None:
                settlement = SettlementRecord.objects.create(
                    settlement_id=settlement_id,
                    project_id=project.external_id,
                    trace_id=trace_id,
                    status=SettlementRecord.Status.REQUESTED,
                    network="testnet",
                    source="hiero-sdk-python",
                )
            else:
                settlement.trace_id = trace_id
                settlement.status = SettlementRecord.Status.REQUESTED
                settlement.transaction_id = ""
                settlement.last_error_code = ""
                settlement.save(update_fields=("trace_id", "status", "transaction_id", "last_error_code", "updated_at"))
            ProjectAuditLog.objects.create(
                project=project,
                actor_id=request.user.email,
                action="HEDERA_TESTNET_TRANSFER_REQUESTED",
                details={
                    "settlement_id": settlement_id,
                    "milestone_id": milestone_id,
                    "amount_hbar": DEMO_PAYMENT_HBAR,
                    "recipient_account_id": settings.FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID,
                    "network": "testnet",
                },
            )
    except IntegrityError:
        return Response({"error": "HEDERA_MILESTONE_ALREADY_PAID"}, status=409)

    try:
        transaction_id = submit_testnet_hbar_transfer(
            operator_id=settings.FW_HEDERA_DEMO_OPERATOR_ACCOUNT_ID,
            private_key=operator_key,
            recipient_id=settings.FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID,
        )
    except HederaPaymentConfigurationError as exc:
        settlement.status = SettlementRecord.Status.FAILED
        settlement.last_error_code = str(exc)
        settlement.save(update_fields=("status", "last_error_code", "updated_at"))
        return Response({"error": str(exc), "settlement_id": settlement_id}, status=503)
    except HederaPaymentSubmissionError as exc:
        settlement.status = (
            SettlementRecord.Status.UNKNOWN if exc.outcome_unknown else SettlementRecord.Status.FAILED
        )
        settlement.last_error_code = exc.code
        settlement.save(update_fields=("status", "last_error_code", "updated_at"))
        return Response({
            "error": exc.code,
            "settlement_id": settlement_id,
            "detail": (
                "Résultat réseau incertain : vérifie HashScan et ne relance pas avant réconciliation."
                if exc.outcome_unknown
                else "Hedera a rejeté le transfert avant confirmation ; vérifie le motif puis tu peux réessayer."
            ),
        }, status=502)

    settlement.status = SettlementRecord.Status.SUBMITTED_BY_OWNER
    settlement.transaction_id = transaction_id
    settlement.save(update_fields=("status", "transaction_id", "updated_at"))
    ProjectAuditLog.objects.create(
        project=project,
        actor_id=request.user.email,
        action="HEDERA_TESTNET_TRANSFER_SUBMITTED",
        details={
            "settlement_id": settlement_id,
            "milestone_id": milestone_id,
            "amount_hbar": DEMO_PAYMENT_HBAR,
            "recipient_account_id": settings.FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID,
            "transaction_id": transaction_id,
            "network": "testnet",
        },
    )
    return Response({
        "settlement_id": settlement_id,
        "status": settlement.status,
        "network": "testnet",
        "transaction_id": transaction_id,
        "hashscan_url": f"https://hashscan.io/testnet/transaction/{transaction_id.replace('@', '-', 1)}",
        "amount_hbar": DEMO_PAYMENT_HBAR,
        "recipient_account_id": settings.FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID,
        "detail": "Reçu Hedera SUCCESS ; la confirmation finale reste suivie séparément par le Mirror Node.",
    }, status=201)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def freelancer_project_members(request, project_id):
    if not _active_freelancer(request):
        return Response({"error": "ACTIVE_FREELANCER_ACCOUNT_REQUIRED"}, status=403)
    project = get_object_or_404(ProjectReference, external_id=project_id, owner=request.user)
    email = str(request.data.get("email", "")).strip().casefold()
    role = str(request.data.get("role", "FREELANCER")).upper()
    if set(request.data) - {"email", "role"} or role not in {"FREELANCER", "CLIENT"} or not email:
        return Response({"error": "INVALID_PROJECT_MEMBER"}, status=400)
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.filter(email__iexact=email).first()
    profile = getattr(user, "freelancer_profile", None) if user else None
    if not user or not profile or profile.status != FreelancerProfile.Status.ACTIVE or profile.role not in {FreelancerProfile.Role.FREELANCER, FreelancerProfile.Role.CLIENT}:
        return Response({"error": "ACTIVE_MEMBER_ACCOUNT_REQUIRED"}, status=404)
    member, created = ProjectMember.objects.get_or_create(project=project, user=user, defaults={"role": role, "added_by": request.user})
    if not created:
        return Response({"error": "PROJECT_MEMBER_EXISTS"}, status=409)
    ProjectAuditLog.objects.create(project=project, actor_id=request.user.email,
                                   action="PROJECT_MEMBER_ADDED", details={"member_user_id": user.pk, "role": role})
    return Response({"email": user.email, "role": member.role, "created_at": member.created_at}, status=201)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def freelancer_project_approval(request, project_id):
    if not _active_freelancer(request):
        return Response({"error": "ACTIVE_FREELANCER_ACCOUNT_REQUIRED"}, status=403)
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    project = ProjectReference.objects.get(external_id=project_id)
    profile = request.user.freelancer_profile
    membership = ProjectMember.objects.filter(project=project, user=request.user, role="CLIENT").exists()
    if profile.role != FreelancerProfile.Role.CLIENT and not membership:
        return Response({"error": "CLIENT_APPROVAL_ROLE_REQUIRED"}, status=403)
    kind = str(request.data.get("kind", "")).upper()
    decision = str(request.data.get("decision", "")).upper()
    milestone_id = str(request.data.get("milestone_id", "")).strip()
    reason = str(request.data.get("reason", ""))[:500]
    if set(request.data) - {"kind", "decision", "milestone_id", "reason"} or kind not in ProjectApproval.Kind.values or decision not in {"APPROVED", "REJECTED"}:
        return Response({"error": "INVALID_APPROVAL"}, status=400)
    milestone = None
    if kind == ProjectApproval.Kind.MILESTONE:
        milestone = ProjectMilestone.objects.filter(project=project, milestone_id=milestone_id).first()
        if not milestone:
            return Response({"error": "MILESTONE_NOT_FOUND"}, status=404)
    if kind == ProjectApproval.Kind.AGREEMENT and not hasattr(project, "agreement"):
        return Response({"error": "AGREEMENT_NOT_FOUND"}, status=404)
    source = "MANUAL"
    approval = ProjectApproval.objects.create(kind=kind, project=project, milestone=milestone, decision=decision,
                                               actor=request.user, reason=reason, provenance=source)
    if kind == ProjectApproval.Kind.AGREEMENT:
        project.agreement.approval_status = decision
        project.agreement.save(update_fields=["approval_status", "updated_at"])
    ProjectAuditLog.objects.create(project=project, actor_id=request.user.email, action="PROJECT_APPROVAL_RECORDED",
                                   details={"kind": kind, "decision": decision, "approval_id": approval.pk})
    return Response({"approval_id": approval.pk, "kind": kind, "decision": decision,
                     "actor": request.user.email, "source": source}, status=201)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def freelancer_complete_milestone(request, project_id, milestone_id):
    if not _active_freelancer(request):
        return Response({"error": "ACTIVE_FREELANCER_ACCOUNT_REQUIRED"}, status=403)
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    if set(request.data) - {"completed_work_units"}:
        return Response({"error": "UNKNOWN_MILESTONE_FIELD"}, status=400)
    milestone = get_object_or_404(ProjectMilestone, project__external_id=project_id, milestone_id=milestone_id)
    if not _can_submit_project_work(request, milestone.project):
        return Response({"error": "FREELANCER_PROJECT_ROLE_REQUIRED"}, status=403)
    units = request.data.get("completed_work_units")
    if isinstance(units, bool) or not isinstance(units, int) or units < 0 or (milestone.planned_work_units is not None and units > milestone.planned_work_units):
        return Response({"error": "INVALID_COMPLETED_WORK_UNITS"}, status=400)
    milestone.completed_work_units = units
    milestone.status = ProjectMilestone.Status.COMPLETED if milestone.planned_work_units == units else ProjectMilestone.Status.IN_PROGRESS
    milestone.provenance = ProjectReference.Provenance.MANUAL
    milestone.save(update_fields=["completed_work_units", "status", "provenance", "updated_at"])
    return Response({"milestone_id": milestone.milestone_id, "status": milestone.status,
                     "completed_work_units": milestone.completed_work_units, "provenance": milestone.provenance,
                     "note": "Déclaration manuelle; elle ne vaut pas vérification de preuve."})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def freelancer_evaluate_policy(request, project_id):
    if not _active_freelancer(request):
        return Response({"error": "ACTIVE_FREELANCER_ACCOUNT_REQUIRED"}, status=403)
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    project = ProjectReference.objects.get(external_id=project_id)
    if not _can_submit_project_work(request, project):
        return Response({"error": "FREELANCER_PROJECT_ROLE_REQUIRED"}, status=403)
    milestone_id = str(request.data.get("milestone_id", "")).strip()
    evidence_event_id = str(request.data.get("evidence_event_id", "")).strip()
    conditions_met = request.data.get("conditions_met")
    risk_level = str(request.data.get("risk_level", "UNKNOWN")).upper()
    if set(request.data) - {"milestone_id", "evidence_event_id", "conditions_met", "risk_level"}:
        return Response({"error": "UNKNOWN_POLICY_FIELD"}, status=400)
    if not milestone_id or not evidence_event_id or conditions_met not in {True, False, None} or risk_level not in {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}:
        return Response({"error": "INVALID_POLICY_INPUT"}, status=400)
    milestone = ProjectMilestone.objects.filter(project=project, milestone_id=milestone_id).first()
    evidence_event = SystemEvent.objects.filter(event_id=evidence_event_id, project_id=project_id, event_type="EVIDENCE_REVIEW_REQUESTED").first()
    planner_event = SystemEvent.objects.filter(project_id=project_id, event_type="ENGAGEMENT_CREATED").order_by("-received_at").first()
    if not milestone or not evidence_event or not planner_event:
        return Response({"error": "CORRELATED_WORKFLOW_INPUT_MISSING"}, status=409)
    if not (planner_event.correlation_id == evidence_event.correlation_id == f"project:{project_id}"):
        return Response({"error": "WORKFLOW_CORRELATION_MISMATCH"}, status=409)
    latest_approval = ProjectApproval.objects.filter(project=project, milestone=milestone, kind="MILESTONE").order_by("-created_at").first()
    client_approved = True if latest_approval and latest_approval.decision == "APPROVED" else False if latest_approval and latest_approval.decision == "REJECTED" else None
    payload = {
        "evaluation_id": f"{project_id}-{milestone_id}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}",
        "milestone_id": milestone_id, "planner_event_id": planner_event.event_id,
        "milestone_complete": milestone.status == ProjectMilestone.Status.COMPLETED,
        "evidence_event_id": evidence_event_id, "client_approved": client_approved,
        "conditions_met": conditions_met, "risk_level": risk_level,
        "source_refs": [planner_event.event_id, evidence_event.event_id] + ([f"approval:{latest_approval.pk}"] if latest_approval else []),
    }
    with transaction.atomic():
        event = _enqueue_local_event(project_id=project_id, event_type="POLICY_EVALUATION_REQUESTED",
                                     payload=payload, correlation_id=f"project:{project_id}", milestone_id=milestone_id)
    return Response({"event_id": event.event_id, "decision": "PENDING", "scope": "LOCAL_SIMULATION_NO_TRANSFER"}, status=202)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def freelancer_submit_test_evidence(request, project_id):
    if not _active_freelancer(request):
        return Response({"error": "ACTIVE_FREELANCER_ACCOUNT_REQUIRED"}, status=403)
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    project = ProjectReference.objects.get(external_id=project_id)
    if not _can_submit_project_work(request, project):
        return Response({"error": "FREELANCER_PROJECT_ROLE_REQUIRED"}, status=403)
    agreement = getattr(project, "agreement", None)
    repository = agreement.github_repository if agreement else ""
    if repository:
        return Response({"error": "TEST_FIXTURE_REQUIRES_NO_LINKED_REPOSITORY", "detail": "Cette action est réservée au test local. Utiliser le connecteur GitHub après validation du dépôt autorisé."}, status=400)
    values = dict(request.data)
    evidence_id = str(values.pop("evidence_id", "")).strip()
    milestone_id = str(values.pop("milestone_id", "")).strip()
    from .serializers import EvidenceReviewRequestedPayloadSerializer
    payload = {"evidence_id": evidence_id, "work_id": milestone_id or f"{project_id}-work",
               "contributor_id": request.user.email, **values}
    validator = EvidenceReviewRequestedPayloadSerializer(data=payload)
    validator.is_valid(raise_exception=True)
    if not evidence_id:
        return Response({"error": "EVIDENCE_ID_REQUIRED"}, status=400)
    if EvidenceSubmission.objects.filter(project=project, evidence_id=evidence_id).exists():
        return Response({"error": "EVIDENCE_ID_CONFLICT"}, status=409)
    milestone = None
    if milestone_id:
        milestone = ProjectMilestone.objects.filter(project=project, milestone_id=milestone_id).first()
        if not milestone:
            return Response({"error": "MILESTONE_NOT_FOUND"}, status=404)
    try:
        with transaction.atomic():
            event = _enqueue_local_event(project_id=project_id, event_type="EVIDENCE_REVIEW_REQUESTED",
                                         payload=validator.validated_data, correlation_id=f"project:{project_id}",
                                         milestone_id=milestone_id or None)
            evidence, created = EvidenceSubmission.objects.get_or_create(
                project=project, evidence_id=evidence_id,
                defaults={"milestone": milestone, "source": "TEST_ONLY", "status": "SUBMITTED",
                          "submitted_by": request.user, "source_event_id": event.event_id, "is_demo_only": True},
            )
            if not created:
                return Response({"error": "EVIDENCE_ID_CONFLICT"}, status=409)
    except IntegrityError:
        return Response({"error": "EVIDENCE_ID_CONFLICT"}, status=409)
    return Response({"evidence_id": evidence.evidence_id, "source": evidence.source, "status": evidence.status,
                     "event_id": event.event_id, "event_status": event.status, "transfer": "NONE"}, status=202)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def freelancer_submit_github_evidence(request, project_id):
    if not _active_freelancer(request):
        return Response({"error": "ACTIVE_FREELANCER_ACCOUNT_REQUIRED"}, status=403)
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    project = ProjectReference.objects.get(external_id=project_id)
    if not _can_submit_project_work(request, project):
        return Response({"error": "FREELANCER_PROJECT_ROLE_REQUIRED"}, status=403)
    agreement = getattr(project, "agreement", None)
    repository = agreement.github_repository if agreement else ""
    if not repository:
        return Response({"error": "PROJECT_GITHUB_REPOSITORY_REQUIRED"}, status=400)
    allowed_repositories = getattr(settings, "FW_GITHUB_ALLOWED_REPOSITORIES", set())
    if repository.casefold() not in allowed_repositories:
        return Response({"error": "GITHUB_REPOSITORY_NOT_ALLOWLISTED"}, status=403)
    profile = request.user.freelancer_profile
    if not profile.github_login:
        return Response({"error": "GITHUB_LOGIN_REQUIRED", "detail": "Renseigne d’abord ton identifiant GitHub dans ton profil."}, status=409)
    body = dict(request.data)
    evidence_id = str(body.pop("evidence_id", "")).strip()
    milestone_id = str(body.pop("milestone_id", "")).strip()
    if str(body.pop("contributor_login", profile.github_login)).casefold() != profile.github_login.casefold():
        return Response({"error": "GITHUB_LOGIN_PROFILE_MISMATCH"}, status=400)
    if set(body) - {"commit_shas", "pull_request_numbers"} or not evidence_id:
        return Response({"error": "INVALID_GITHUB_EVIDENCE_REQUEST"}, status=400)
    milestone = None
    if milestone_id:
        milestone = ProjectMilestone.objects.filter(project=project, milestone_id=milestone_id).first()
        if not milestone:
            return Response({"error": "MILESTONE_NOT_FOUND"}, status=404)
    if EvidenceSubmission.objects.filter(project=project, evidence_id=evidence_id).exists():
        return Response({"error": "EVIDENCE_ID_CONFLICT"}, status=409)
    from .serializers import EvidenceReviewRequestedPayloadSerializer
    payload = {"evidence_id": evidence_id, "work_id": milestone_id or f"{project_id}-work",
               "contributor_id": request.user.email, "contributor_login": profile.github_login,
               "contributor_identity_verified": False, "repository": repository, **body}
    validator = EvidenceReviewRequestedPayloadSerializer(data=payload)
    validator.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            event = _enqueue_local_event(project_id=project_id, event_type="EVIDENCE_REVIEW_REQUESTED",
                                         payload=validator.validated_data, correlation_id=f"project:{project_id}",
                                         milestone_id=milestone_id or None)
            EvidenceSubmission.objects.create(
                project=project, milestone=milestone, evidence_id=evidence_id, source="GITHUB_API",
                status="SUBMITTED", repository=repository, submitted_by=request.user,
                source_event_id=event.event_id, is_demo_only=project.is_demo_only,
            )
    except IntegrityError:
        return Response({"error": "EVIDENCE_ID_CONFLICT"}, status=409)
    return Response({"evidence_id": evidence_id, "source": "GITHUB_API", "status": "SUBMITTED",
                     "repository": repository, "event_id": event.event_id,
                     "identity_source": "PROFILE_GITHUB_LOGIN_CLAIM", "transfer": "NONE"}, status=202)


@api_view(["GET", "POST"])
def project_registry(request):
    if request.method == "GET":
        operator_id = _operator_id(request)
        if operator_id:
            queryset = ProjectReference.objects.all()
        elif _active_freelancer(request):
            queryset = ProjectReference.objects.filter(owner=request.user)
        else:
            return Response({"error": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)
        projects = ProjectReferenceSerializer(queryset, many=True).data
        return Response({"count": len(projects), "results": projects, "source": "local-registry"})

    actor_id = _operator_id(request)
    if actor_id is None:
        return Response({"error": "OPERATOR_AUTH_FAILED"}, status=status.HTTP_401_UNAUTHORIZED)
    serializer = ProjectInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = dict(serializer.validated_data)
    for agreement_field in ("budget_amount", "currency", "total_hours", "total_work_units", "start_date",
                            "target_deadline", "github_repository", "conditions"):
        values.pop(agreement_field, None)
    try:
        with transaction.atomic():
            project = ProjectReference.objects.create(
                **values,
                provenance=ProjectReference.Provenance.MANUAL,
                created_by=actor_id,
            )
            ProjectAuditLog.objects.create(
                project=project, actor_id=actor_id, action="PROJECT_CREATED_MANUAL",
                details={"provenance": project.provenance, "source_record_id": project.source_record_id},
            )
    except IntegrityError:
        return Response({"error": "PROJECT_ID_CONFLICT", "project_id": values["external_id"]}, status=409)
    return Response(ProjectReferenceSerializer(project).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def project_import_preview(request):
    actor_id = _operator_id(request)
    if actor_id is None:
        return Response({"error": "OPERATOR_AUTH_FAILED"}, status=status.HTTP_401_UNAUTHORIZED)
    if not request.FILES and isinstance(request.data, dict):
        unknown = set(request.data) - {"projects"}
        if unknown:
            return Response({"error": "UNKNOWN_IMPORT_FIELD", "fields": sorted(str(item) for item in unknown)}, status=400)
    rows, file_sha256, file_name = extract_import_rows(request)
    accepted, rejected = validate_import_rows(rows)
    batch = ProjectImportBatch.objects.create(
        file_name=file_name,
        file_sha256=file_sha256,
        accepted_rows=accepted,
        rejected_rows=rejected,
        actor_id=actor_id,
    )
    return Response({
        "batch_id": str(batch.batch_id), "status": batch.status,
        "file_name": batch.file_name, "file_sha256": batch.file_sha256,
        "accepted_count": len(accepted), "rejected_count": len(rejected),
        "accepted": accepted, "rejected": rejected,
        "commit_url": f"/api/projects/imports/{batch.batch_id}/commit",
    }, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def project_import_commit(request, batch_id):
    actor_id = _operator_id(request)
    if actor_id is None:
        return Response({"error": "OPERATOR_AUTH_FAILED"}, status=status.HTTP_401_UNAUTHORIZED)
    batch = get_object_or_404(ProjectImportBatch, batch_id=batch_id)
    if batch.actor_id != actor_id:
        return Response({"error": "IMPORT_ACTOR_MISMATCH"}, status=status.HTTP_403_FORBIDDEN)
    if batch.status != ProjectImportBatch.Status.PREVIEW:
        return Response({"error": "IMPORT_ALREADY_COMMITTED"}, status=status.HTTP_409_CONFLICT)
    if not batch.accepted_rows:
        return Response({"error": "IMPORT_HAS_NO_VALID_ROWS"}, status=status.HTTP_400_BAD_REQUEST)
    created = []
    try:
        with transaction.atomic():
            for values in batch.accepted_rows:
                values = dict(values)
                for agreement_field in ("budget_amount", "currency", "total_hours", "total_work_units", "start_date",
                                        "target_deadline", "github_repository", "conditions"):
                    values.pop(agreement_field, None)
                project = ProjectReference.objects.create(
                    **values,
                    provenance=ProjectReference.Provenance.IMPORTED,
                    created_by=actor_id,
                    import_batch=batch,
                )
                ProjectAuditLog.objects.create(
                    project=project, batch=batch, actor_id=actor_id, action="PROJECT_IMPORTED",
                    details={"file_sha256": batch.file_sha256, "source_record_id": project.source_record_id},
                )
                created.append(project)
            batch.status = ProjectImportBatch.Status.IMPORTED
            batch.imported_at = timezone.now()
            batch.save(update_fields=("status", "imported_at"))
    except IntegrityError:
        return Response({"error": "PROJECT_ID_CONFLICT", "detail": "Un projet a été créé depuis cette prévisualisation; refaire l'aperçu."}, status=409)
    return Response({"batch_id": str(batch.batch_id), "status": batch.status, "imported_count": len(created), "projects": ProjectReferenceSerializer(created, many=True).data})


@api_view(["GET"])
def project_activity(request, project_id):
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    events = SystemEvent.objects.filter(project_id=project_id).order_by("-received_at")[:100]
    results = [
        {
            "kind": "EVENT",
            "event_id": row.event_id,
            "event_type": row.event_type,
            "project_id": row.project_id,
            "trace_id": row.trace_id,
            "correlation_id": row.correlation_id,
            "status": row.status,
            "processing_status": row.outbox.status if hasattr(row, "outbox") else "LEGACY",
            "source": row.source,
            "at": row.received_at,
        }
        for row in events
    ]
    actions = AgentAction.objects.filter(project_id=project_id).select_related("agent", "event")[:100]
    results.extend(
        {
            "kind": "AGENT_ACTION",
            "event_id": row.event.event_id,
            "agent_id": row.agent.key,
            "trace_id": row.trace_id,
            "correlation_id": row.event.correlation_id,
            "status": row.status,
            "summary": row.summary,
            "at": row.created_at,
        }
        for row in actions
    )
    project_audit = ProjectAuditLog.objects.filter(project__external_id=project_id).select_related("project")[:100]
    results.extend(
        {
            "kind": "PROJECT_AUDIT",
            "event_id": row.project.external_id,
            "project_id": row.project.external_id,
            "trace_id": "",
            "status": row.action,
            "summary": row.action.replace("_", " "),
            "actor_id": row.actor_id,
            "at": row.created_at,
        }
        for row in project_audit
    )
    results.sort(key=lambda item: item["at"], reverse=True)
    return Response({"project_id": project_id, "count": len(results), "results": results[:200]})


@api_view(["GET"])
def project_alerts(request, project_id):
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    queryset = AgentAlert.objects.filter(project_id=project_id)
    if request.query_params.get("active", "true").lower() == "true":
        queryset = queryset.filter(resolved_at__isnull=True)
    results = [
        {
            "id": row.id,
            "type": row.alert_type,
            "severity": row.severity,
            "title": row.title,
            "trace_id": row.trace_id,
            "details": row.details,
            "created_at": row.created_at,
            "resolved_at": row.resolved_at,
        }
        for row in queryset.order_by("-created_at")[:100]
    ]
    return Response({"project_id": project_id, "count": len(results), "results": results})


@api_view(["GET"])
def project_metrics(request, project_id):
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    snapshot, error_response = _project_snapshot_or_response(project_id)
    if error_response:
        return error_response
    metric_values = [
        {"key": "progress_percent", "value": snapshot["progress_percent"], "unit": "%"},
        {"key": "units_completed", "value": snapshot["units"]["completed"], "unit": "units"},
        {"key": "milestones_completed", "value": snapshot["milestones"]["completed"], "unit": "milestones"},
        {"key": "evidence_verified", "value": snapshot["evidence"]["verified"], "unit": "items"},
        {"key": "open_risk_items", "value": snapshot["risk"]["open_items"], "unit": "items"},
        {"key": "settlements_pending", "value": snapshot["settlements"]["pending"], "unit": "transactions"},
    ]
    history = DashboardMetric.objects.filter(project_id=project_id).order_by("measured_at")[:500]
    return Response(
        {
            "project_id": project_id,
            "source": snapshot["source"],
            "metrics": metric_values,
            "history": [
                {"key": row.metric_key, "value": row.value, "unit": row.unit, "source": row.source, "measured_at": row.measured_at}
                for row in history
            ],
        }
    )


@api_view(["GET"])
def hedera_activity(request, project_id):
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    local_project = ProjectReference.objects.filter(external_id=project_id).exists()
    if local_project and settings.FW_MODE_HEDERA != "live":
        return Response({"project_id": project_id, "count": 0, "results": [], "source": "not-configured"})
    adapter, error_response = _hedera_adapter_or_response()
    if error_response:
        return error_response
    if settings.FW_MODE_HEDERA == "live" and not adapter.is_configured(project_id):
        return Response({"project_id": project_id, "count": 0, "results": [], "source": "not-configured"})
    try:
        results = adapter.get_activity(project_id)
    except KeyError:
        return Response({"error": "PROJECT_NOT_FOUND", "project_id": project_id}, status=404)
    except HederaObserverUnavailable as exc:
        return Response({"error": "HEDERA_SOURCE_UNAVAILABLE", "source_status": "UNAVAILABLE", "detail": str(exc)}, status=503)
    return Response({"project_id": project_id, "count": len(results), "results": results, "source": adapter.source})


@api_view(["GET"])
def hedera_transactions(request, project_id):
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    local_project = ProjectReference.objects.filter(external_id=project_id).exists()
    if local_project and settings.FW_MODE_HEDERA != "live":
        return Response({"project_id": project_id, "count": 0, "results": [], "source": "not-configured"})
    adapter, error_response = _hedera_adapter_or_response()
    if error_response:
        return error_response
    if settings.FW_MODE_HEDERA == "live" and not adapter.is_configured(project_id):
        return Response({"project_id": project_id, "count": 0, "results": [], "source": "not-configured"})
    try:
        results = adapter.get_transactions(project_id)
    except KeyError:
        return Response({"error": "PROJECT_NOT_FOUND", "project_id": project_id}, status=404)
    except HederaObserverUnavailable as exc:
        return Response({"error": "HEDERA_SOURCE_UNAVAILABLE", "source_status": "UNAVAILABLE", "detail": str(exc)}, status=503)
    return Response({"project_id": project_id, "count": len(results), "results": results, "source": adapter.source})


@api_view(["GET"])
def project_dashboard(request, project_id):
    denied = _project_access_error(request, project_id)
    if denied:
        return denied
    snapshot, error_response = _project_snapshot_or_response(project_id)
    if error_response:
        return error_response
    ensure_mock_agents()
    agent_rows = AgentSerializer(Agent.objects.all(), many=True).data
    activity = [
        {
            "agent_id": row.agent.key,
            "event_id": row.event.event_id,
            "trace_id": row.trace_id,
            "correlation_id": row.event.correlation_id,
            "status": row.status,
            "summary": row.summary,
            "at": row.created_at,
        }
        for row in AgentAction.objects.filter(project_id=project_id).select_related("agent", "event")[:10]
    ]
    alerts = [
        {
            "type": row.alert_type,
            "severity": row.severity,
            "title": row.title,
            "trace_id": row.trace_id,
            "created_at": row.created_at,
        }
        for row in AgentAlert.objects.filter(project_id=project_id, resolved_at__isnull=True).order_by("-created_at")[:10]
    ]
    hedera_mode = settings.FW_MODE_HEDERA
    local_project = snapshot.get("source") == "local-registry"
    if local_project and hedera_mode != "live":
        # Demo fixtures are never attached to a registered project.
        hedera_feed = []
        hedera_transactions = []
        hedera_source = "not-configured"
        hedera_status = "no_observations"
    else:
        try:
            hedera_adapter = get_hedera_adapter(hedera_mode)
            if hedera_mode == "live" and not hedera_adapter.is_configured(project_id):
                hedera_feed = []
                hedera_transactions = []
                hedera_source = "not-configured"
                hedera_status = "no_observations"
            else:
                hedera_feed = hedera_adapter.get_activity(project_id)
                hedera_transactions = hedera_adapter.get_transactions(project_id)
                hedera_source = hedera_adapter.source
                hedera_status = "available"
        except NotImplementedError:
            hedera_feed = []
            hedera_transactions = []
            hedera_source = hedera_mode
            hedera_status = "adapter_not_implemented"
        except HederaObserverUnavailable:
            hedera_feed = []
            hedera_transactions = []
            hedera_source = hedera_mode
            hedera_status = "UNAVAILABLE"
        except KeyError:
            return Response({"error": "PROJECT_NOT_FOUND", "project_id": project_id}, status=404)
    outbox_counts = {
        code.lower(): EventOutbox.objects.filter(event__project_id=project_id, status=code).count()
        for code, _label in EventOutbox.Status.choices
    }
    return Response(
        {
            "project": snapshot,
            "agents": agent_rows,
            "agent_activity": activity,
            "alerts": alerts,
            "hedera_activity": hedera_feed,
            "hedera_transactions": hedera_transactions,
            "sources": {
                "project": snapshot["source"],
                "events": settings.FW_MODE_EVENTS,
                "evidence": settings.FW_MODE_EVIDENCE,
                "hedera": hedera_source,
            },
            "source_status": {"hedera": hedera_status},
            "event_queue": outbox_counts,
            "generated_at": timezone.now(),
        }
    )


@api_view(["POST"])
def ingest_event(request):
    api_keys = settings.FW_INGEST_API_KEYS
    producer_header = request.headers.get("X-Producer-ID", "")
    presented_key = request.headers.get("X-API-Key", "")
    if api_keys:
        expected_key = api_keys.get(producer_header, "")
        if not expected_key or not hmac.compare_digest(presented_key, expected_key):
            return Response({"error": "PRODUCER_AUTH_FAILED"}, status=status.HTTP_401_UNAUTHORIZED)
    elif settings.FW_INGEST_AUTH_REQUIRED:
        return Response({"error": "INGEST_AUTH_NOT_CONFIGURED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    serializer = IngestEventSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    event_data = serializer.validated_data
    if api_keys:
        if event_data.get("producer_id") and event_data["producer_id"] != producer_header:
            return Response({"error": "PRODUCER_ID_MISMATCH"}, status=status.HTTP_400_BAD_REQUEST)
        event_data["producer_id"] = producer_header
    payload_hash = canonical_payload_hash(event_data["payload"])

    existing = SystemEvent.objects.filter(event_id=event_data["event_id"]).first()
    if existing:
        if (
            existing.payload_sha256 != payload_hash
            or existing.event_type != event_data["event_type"]
            or existing.project_id != event_data["project_id"]
            or existing.milestone_id != event_data.get("milestone_id")
            or existing.occurred_at != event_data["occurred_at"]
            or existing.source != event_data["source"]
            or existing.schema_version != event_data.get("schema_version", "1.0")
            or existing.producer_id != event_data.get("producer_id", "")
            or existing.correlation_id != event_data.get("correlation_id")
        ):
            _audit_event_conflict(existing, event_data, payload_hash)
            return Response(
                {"error": "EVENT_ID_CONFLICT", "message": "event_id déjà utilisé pour un contenu différent."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(_event_accepted(existing, duplicate=True), status=status.HTTP_200_OK)

    ensure_mock_agents()
    try:
        from uuid import uuid4

        stored_data = dict(event_data)
        stored_data["payload"] = redact_sensitive(event_data["payload"])
        with transaction.atomic():
            event = SystemEvent.objects.create(
                **stored_data,
                payload_sha256=payload_hash,
                trace_id=f"FW-TRACE-{timezone.now():%Y%m%d}-{uuid4().hex[:12].upper()}",
            )
            AuditLog.objects.create(
                event=event,
                project_id=event.project_id,
                trace_id=event.trace_id,
                event_type=event.event_type,
                action="EVENT_INGESTED",
                status=event.status,
                details={"source": event.source, "producer_id": event.producer_id, "schema_version": event.schema_version, "payload_sha256": payload_hash},
            )
            EventOutbox.objects.create(event=event)
    except IntegrityError:
        # A concurrent retry may win the unique event_id race. Resolve it idempotently.
        event = SystemEvent.objects.get(event_id=event_data["event_id"])
        if (
            event.payload_sha256 != payload_hash
            or event.event_type != event_data["event_type"]
            or event.project_id != event_data["project_id"]
            or event.milestone_id != event_data.get("milestone_id")
            or event.occurred_at != event_data["occurred_at"]
            or event.source != event_data["source"]
            or event.schema_version != event_data.get("schema_version", "1.0")
            or event.producer_id != event_data.get("producer_id", "")
            or event.correlation_id != event_data.get("correlation_id")
        ):
            _audit_event_conflict(event, event_data, payload_hash)
            return Response({"error": "EVENT_ID_CONFLICT"}, status=status.HTTP_409_CONFLICT)
        return Response(_event_accepted(event, duplicate=True), status=status.HTTP_200_OK)
    except OperationalError as exc:
        if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
            raise
        response = Response(
            {"error": "SQLITE_BUSY", "detail": "Écriture momentanément indisponible; réessayer avec le même event_id."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        response["Retry-After"] = "1"
        return response

    return Response(_event_accepted(event, duplicate=False), status=status.HTTP_202_ACCEPTED)


def _event_accepted(event, *, duplicate):
    return {
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "status": event.status,
        "duplicate": duplicate,
        "received_at": event.received_at,
        "processing_status": event.outbox.status if hasattr(event, "outbox") else "UNKNOWN",
    }


def _audit_event_conflict(existing, attempted, attempted_hash):
    AuditLog.objects.create(
        event=existing,
        project_id=existing.project_id,
        trace_id=existing.trace_id,
        event_type=existing.event_type,
        action="EVENT_ID_CONFLICT",
        status="REJECTED",
        details={
            "attempted_event_type": attempted.get("event_type", ""),
            "attempted_source": attempted.get("source", ""),
            "attempted_producer_id": attempted.get("producer_id", ""),
            "attempted_payload_sha256": attempted_hash,
        },
    )
