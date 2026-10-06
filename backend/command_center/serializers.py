from rest_framework import serializers
from django.utils import timezone
from datetime import timedelta
import json


EVENT_TYPES = (
    "ENGAGEMENT_CREATED",
    "WORK_CREATED",
    "EVIDENCE_REVIEW_REQUESTED",
    "WORK_UNIT_COMPLETED",
    "EVIDENCE_SUBMITTED",
    "EVIDENCE_VERIFIED",
    "MILESTONE_COMPLETED",
    "POLICY_DECIDED",
    "POLICY_EVALUATION_REQUESTED",
    "SETTLEMENT_REQUESTED",
    "SETTLEMENT_UPDATED",
    "HEDERA_TRANSACTION_OBSERVED",
    "AGENT_STATUS_CHANGED",
    "SYSTEM_ALERT_RAISED",
    "MILESTONE_DELAYED",
    "EVIDENCE_MISSING",
    "HIGH_RISK",
    "TRANSACTION_FAILED",
    "AGENT_BLOCKED",
    "HEDERA_ERROR",
)

LOCAL_CONTRACT_VERSION = "dev4-local/1.0"
LOCAL_CONTRACT_V2_VERSION = "dev4-local/2.0"


class ClosedPayloadSerializer(serializers.Serializer):
    """Internal, provisional contract payloads for isolated Dev 4 tests."""

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({str(field): "Champ payload inconnu." for field in sorted(unknown, key=str)})
        return attrs


class WorkCreatedPayloadSerializer(ClosedPayloadSerializer):
    work_id = serializers.CharField(min_length=1, max_length=128)
    title = serializers.CharField(min_length=1, max_length=180)


class WorkUnitCompletedPayloadSerializer(ClosedPayloadSerializer):
    work_id = serializers.CharField(min_length=1, max_length=128)
    completed_work_units = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class MilestoneCompletedPayloadSerializer(ClosedPayloadSerializer):
    milestone_id = serializers.CharField(min_length=1, max_length=128)
    completed_work_units = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class EvidenceVerdictPayloadSerializer(ClosedPayloadSerializer):
    evidence_id = serializers.CharField(min_length=1, max_length=128)
    verdict = serializers.ChoiceField(choices=("VERIFIED", "REJECTED", "UNKNOWN"))
    reason_code = serializers.CharField(max_length=80, required=False, allow_blank=True)


class AgentStatusChangedPayloadSerializer(ClosedPayloadSerializer):
    agent_key = serializers.CharField(min_length=1, max_length=40)
    status = serializers.ChoiceField(choices=("IDLE", "RUNNING", "BLOCKED", "OFFLINE"))
    reason_code = serializers.CharField(max_length=80, required=False, allow_blank=True)


class SystemAlertPayloadSerializer(ClosedPayloadSerializer):
    alert_type = serializers.CharField(min_length=1, max_length=64)
    title = serializers.CharField(min_length=1, max_length=180)
    severity = serializers.ChoiceField(choices=("INFO", "WARNING", "HIGH", "CRITICAL"))
    details = serializers.DictField(required=False, default=dict)


class MilestoneDelayedPayloadSerializer(ClosedPayloadSerializer):
    milestone_id = serializers.CharField(min_length=1, max_length=128)
    target_date = serializers.DateField(required=False, allow_null=True)
    reason_code = serializers.CharField(max_length=80, required=False, allow_blank=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("target_date"):
            attrs["target_date"] = attrs["target_date"].isoformat()
        return attrs


class EvidenceMissingPayloadSerializer(ClosedPayloadSerializer):
    evidence_id = serializers.CharField(min_length=1, max_length=128)
    milestone_id = serializers.CharField(min_length=1, max_length=128, required=False, allow_blank=True)
    reason_code = serializers.CharField(min_length=1, max_length=80)


class HighRiskPayloadSerializer(ClosedPayloadSerializer):
    risk_level = serializers.ChoiceField(choices=("HIGH", "UNKNOWN"))
    reason_code = serializers.CharField(min_length=1, max_length=80)


class TransactionFailedPayloadSerializer(ClosedPayloadSerializer):
    settlement_id = serializers.CharField(min_length=1, max_length=128)
    failure_code = serializers.CharField(min_length=1, max_length=80)
    transaction_id = serializers.CharField(max_length=128, required=False, allow_blank=True)


class AgentBlockedPayloadSerializer(ClosedPayloadSerializer):
    agent_key = serializers.CharField(min_length=1, max_length=40)
    reason_code = serializers.CharField(min_length=1, max_length=80)


class HederaErrorPayloadSerializer(ClosedPayloadSerializer):
    service = serializers.CharField(min_length=1, max_length=64)
    reason_code = serializers.CharField(min_length=1, max_length=80)
    details = serializers.DictField(required=False, default=dict)


class EngagementCreatedPayloadSerializer(ClosedPayloadSerializer):
    agreement_id = serializers.CharField(min_length=1, max_length=128)
    title = serializers.CharField(min_length=1, max_length=180)
    total_hours = serializers.IntegerField(min_value=1, max_value=100000)
    total_work_units = serializers.IntegerField(min_value=1, max_value=100000)
    start_date = serializers.DateField(required=False, allow_null=True)
    target_deadline = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        start_date = attrs.get("start_date")
        deadline = attrs.get("target_deadline")
        if start_date and deadline and deadline < start_date:
            raise serializers.ValidationError({"target_deadline": "La deadline ne peut pas précéder le début du projet."})
        if start_date:
            attrs["start_date"] = start_date.isoformat()
        if deadline:
            attrs["target_deadline"] = deadline.isoformat()
        return attrs


class CommitEvidenceSerializer(serializers.Serializer):
    sha = serializers.RegexField(r"^[a-fA-F0-9]{7,64}$")
    author_id = serializers.CharField(min_length=1, max_length=128)


class PullRequestEvidenceSerializer(serializers.Serializer):
    number = serializers.IntegerField(min_value=1)
    author_id = serializers.CharField(min_length=1, max_length=128)
    state = serializers.ChoiceField(choices=("OPEN", "MERGED", "CLOSED"))
    commit_shas = serializers.ListField(child=serializers.RegexField(r"^[a-fA-F0-9]{7,64}$"), max_length=100, required=False, default=list)


class ReviewEvidenceSerializer(serializers.Serializer):
    pull_request_number = serializers.IntegerField(min_value=1)
    reviewer_id = serializers.CharField(min_length=1, max_length=128)
    state = serializers.ChoiceField(choices=("APPROVED", "CHANGES_REQUESTED", "COMMENTED"))


class EvidenceReviewRequestedPayloadSerializer(ClosedPayloadSerializer):
    evidence_id = serializers.CharField(min_length=1, max_length=128)
    work_id = serializers.CharField(min_length=1, max_length=128)
    contributor_id = serializers.CharField(min_length=1, max_length=128)
    repository = serializers.RegexField(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", required=False)
    contributor_login = serializers.CharField(min_length=1, max_length=128, required=False)
    contributor_identity_verified = serializers.BooleanField(required=False)
    commit_shas = serializers.ListField(child=serializers.RegexField(r"^[a-fA-F0-9]{7,64}$"), max_length=3, required=False, default=list)
    pull_request_numbers = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=3, required=False, default=list)
    # These fields are permitted only for explicitly local, synthetic scenarios.
    commits = CommitEvidenceSerializer(many=True, max_length=200, required=False, default=list)
    pull_requests = PullRequestEvidenceSerializer(many=True, max_length=50, required=False, default=list)
    reviews = ReviewEvidenceSerializer(many=True, max_length=100, required=False, default=list)
    ci_status = serializers.ChoiceField(choices=("SUCCESS", "FAILURE", "PENDING"), required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("repository"):
            if not attrs.get("contributor_login") or not attrs.get("commit_shas") or not attrs.get("pull_request_numbers"):
                raise serializers.ValidationError("Le mode GitHub requiert contributor_login et des références de commit et PR.")
        elif not all(field in self.initial_data for field in ("commits", "pull_requests", "reviews", "ci_status")):
            raise serializers.ValidationError("Fournir repository avec des références GitHub, ou des données synthétiques locales.")
        return attrs


class PolicyEvaluationRequestedPayloadSerializer(ClosedPayloadSerializer):
    evaluation_id = serializers.CharField(min_length=1, max_length=128)
    settlement_id = serializers.CharField(max_length=128, required=False, allow_blank=False)
    milestone_id = serializers.CharField(min_length=1, max_length=128)
    planner_event_id = serializers.CharField(min_length=1, max_length=128)
    milestone_complete = serializers.BooleanField(allow_null=True)
    evidence_event_id = serializers.CharField(min_length=1, max_length=128)
    client_approved = serializers.BooleanField(allow_null=True)
    conditions_met = serializers.BooleanField(allow_null=True)
    risk_level = serializers.ChoiceField(choices=("LOW", "MEDIUM", "HIGH", "UNKNOWN"))
    source_refs = serializers.ListField(child=serializers.CharField(max_length=128), max_length=50)


class EvidenceSubmittedPayloadSerializer(ClosedPayloadSerializer):
    evidence_id = serializers.CharField(min_length=1, max_length=128)
    work_id = serializers.CharField(min_length=1, max_length=128)
    content_sha256 = serializers.RegexField(r"^[a-fA-F0-9]{64}$")


class PolicyDecidedPayloadSerializer(ClosedPayloadSerializer):
    decision_id = serializers.CharField(min_length=1, max_length=128)
    settlement_id = serializers.CharField(max_length=128, required=False, allow_blank=False)
    decision = serializers.ChoiceField(choices=("ALLOW", "BLOCK", "HUMAN_REVIEW"))
    reason_code = serializers.CharField(min_length=1, max_length=80)
    policy_version = serializers.CharField(min_length=1, max_length=40)


class SettlementUpdatedPayloadSerializer(ClosedPayloadSerializer):
    settlement_id = serializers.CharField(min_length=1, max_length=128)
    status = serializers.ChoiceField(choices=("PENDING", "SUBMITTED", "CONFIRMED", "FAILED", "REVERSED"))
    transaction_id = serializers.CharField(max_length=128, required=False, allow_blank=True)
    network = serializers.CharField(max_length=40, required=False, allow_blank=True)
    finality_confirmed = serializers.BooleanField(required=False, default=False)
    consensus_timestamp = serializers.CharField(max_length=64, required=False, allow_blank=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["status"] in {"SUBMITTED", "CONFIRMED"} and not attrs.get("transaction_id"):
            raise serializers.ValidationError({"transaction_id": "Une référence de transaction est requise pour SUBMITTED ou CONFIRMED."})
        if attrs["status"] == "CONFIRMED" and (not attrs.get("finality_confirmed") or not attrs.get("consensus_timestamp")):
            raise serializers.ValidationError({"status": "CONFIRMED requiert la finalité et son horodatage source."})
        return attrs


class SettlementRequestedPayloadSerializer(ClosedPayloadSerializer):
    settlement_id = serializers.CharField(min_length=1, max_length=128)


class HederaSettlementObservedPayloadSerializer(SettlementUpdatedPayloadSerializer):
    status = serializers.ChoiceField(choices=("PENDING", "CONFIRMED", "FAILED"))


LOCAL_PAYLOAD_SERIALIZERS = {
    "ENGAGEMENT_CREATED": EngagementCreatedPayloadSerializer,
    "WORK_CREATED": WorkCreatedPayloadSerializer,
    "WORK_UNIT_COMPLETED": WorkUnitCompletedPayloadSerializer,
    "MILESTONE_COMPLETED": MilestoneCompletedPayloadSerializer,
    "EVIDENCE_REVIEW_REQUESTED": EvidenceReviewRequestedPayloadSerializer,
    "EVIDENCE_SUBMITTED": EvidenceSubmittedPayloadSerializer,
    "EVIDENCE_VERIFIED": EvidenceVerdictPayloadSerializer,
    "EVIDENCE_MISSING": EvidenceMissingPayloadSerializer,
    "MILESTONE_DELAYED": MilestoneDelayedPayloadSerializer,
    "HIGH_RISK": HighRiskPayloadSerializer,
    "TRANSACTION_FAILED": TransactionFailedPayloadSerializer,
    "AGENT_BLOCKED": AgentBlockedPayloadSerializer,
    "HEDERA_ERROR": HederaErrorPayloadSerializer,
    "AGENT_STATUS_CHANGED": AgentStatusChangedPayloadSerializer,
    "SYSTEM_ALERT_RAISED": SystemAlertPayloadSerializer,
    "POLICY_DECIDED": PolicyDecidedPayloadSerializer,
    "POLICY_EVALUATION_REQUESTED": PolicyEvaluationRequestedPayloadSerializer,
    "SETTLEMENT_REQUESTED": SettlementRequestedPayloadSerializer,
    "SETTLEMENT_UPDATED": SettlementUpdatedPayloadSerializer,
    "HEDERA_TRANSACTION_OBSERVED": HederaSettlementObservedPayloadSerializer,
}


class IngestEventSerializer(serializers.Serializer):
    schema_version = serializers.CharField(max_length=24, required=False, default="1.0")
    producer_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    event_id = serializers.CharField(min_length=1, max_length=128)
    event_type = serializers.ChoiceField(choices=EVENT_TYPES)
    project_id = serializers.CharField(min_length=1, max_length=128)
    milestone_id = serializers.CharField(max_length=128, required=False, allow_null=True, allow_blank=False)
    occurred_at = serializers.DateTimeField()
    source = serializers.CharField(min_length=1, max_length=128)
    payload = serializers.DictField()
    correlation_id = serializers.CharField(max_length=128, required=False, allow_null=True, allow_blank=False)

    def validate(self, attrs):
        unknown_fields = set(self.initial_data) - set(self.fields)
        if unknown_fields:
            raise serializers.ValidationError({field: "Champ non défini dans le contrat." for field in sorted(unknown_fields)})
        if len(json.dumps(self.initial_data, ensure_ascii=False, default=str).encode("utf-8")) > 256 * 1024:
            raise serializers.ValidationError({"code": "EVENT_TOO_LARGE", "detail": "Maximum envelope size is 256 KiB."})
        if attrs["occurred_at"].utcoffset() is None:
            raise serializers.ValidationError({"occurred_at": "Un fuseau horaire explicite est requis."})
        if attrs["schema_version"] not in {"1.0", LOCAL_CONTRACT_VERSION, LOCAL_CONTRACT_V2_VERSION}:
            raise serializers.ValidationError({"schema_version": "Version de contrat Dev 4 non prise en charge."})
        if attrs["schema_version"] in {LOCAL_CONTRACT_VERSION, LOCAL_CONTRACT_V2_VERSION}:
            if attrs["schema_version"] == LOCAL_CONTRACT_V2_VERSION and (not attrs.get("producer_id") or not attrs.get("correlation_id")):
                raise serializers.ValidationError({"contract": "Le contrat 2.0 exige producer_id et correlation_id."})
            payload_serializer = LOCAL_PAYLOAD_SERIALIZERS.get(attrs["event_type"])
            if payload_serializer is None:
                raise serializers.ValidationError({"event_type": "Type non défini dans le contrat Dev 4 local."})
            validator = payload_serializer(data=attrs["payload"])
            validator.is_valid(raise_exception=True)
            attrs["payload"] = validator.validated_data
        return attrs


class ProjectInputSerializer(serializers.Serializer):
    external_id = serializers.CharField(min_length=1, max_length=128, trim_whitespace=True)
    title = serializers.CharField(min_length=1, max_length=180, trim_whitespace=True)
    status = serializers.CharField(max_length=40, required=False, default="UNKNOWN", trim_whitespace=True)
    description = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    source_record_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    budget_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False, allow_null=True)
    currency = serializers.CharField(max_length=12, required=False, allow_blank=True, default="")
    total_hours = serializers.IntegerField(min_value=1, max_value=100000, required=False, allow_null=True)
    total_work_units = serializers.IntegerField(min_value=1, max_value=100000, required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    target_deadline = serializers.DateField(required=False, allow_null=True)
    github_repository = serializers.RegexField(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", required=False, allow_blank=True, default="")
    conditions = serializers.ListField(child=serializers.CharField(max_length=500), max_length=50, required=False, default=list)

    def validate(self, attrs):
        unknown_fields = set(self.initial_data) - set(self.fields)
        if unknown_fields:
            raise serializers.ValidationError({str(field): "Champ projet inconnu." for field in sorted(unknown_fields, key=str)})
        if attrs.get("start_date") and attrs.get("target_deadline") and attrs["target_deadline"] < attrs["start_date"]:
            raise serializers.ValidationError({"target_deadline": "La deadline ne peut pas précéder la date de début."})
        return attrs


class ProjectReferenceSerializer(serializers.Serializer):
    project_id = serializers.CharField(source="external_id")
    title = serializers.CharField()
    status = serializers.CharField()
    description = serializers.CharField()
    provenance = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    demo_only = serializers.BooleanField(source="is_demo_only", read_only=True)


class AgentSerializer(serializers.Serializer):
    id = serializers.CharField(source="key")
    name = serializers.CharField(source="display_name")
    status = serializers.CharField()
    capabilities = serializers.ListField(child=serializers.CharField())
    last_activity_at = serializers.DateTimeField(allow_null=True)
    last_heartbeat_at = serializers.DateTimeField(allow_null=True)
    agent_version = serializers.CharField()
    last_error_code = serializers.CharField()
    health_status = serializers.SerializerMethodField()

    def get_health_status(self, obj):
        if obj.last_heartbeat_at is None:
            return "UNKNOWN"
        return "AVAILABLE" if obj.last_heartbeat_at >= timezone.now() - timedelta(seconds=30) else "STALE"
