import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def new_span_id():
    return uuid.uuid4().hex[:16]


class Agent(models.Model):
    class Status(models.TextChoices):
        IDLE = "IDLE", "Idle"
        RUNNING = "RUNNING", "Running"
        BLOCKED = "BLOCKED", "Blocked"
        OFFLINE = "OFFLINE", "Offline"

    key = models.CharField(max_length=40, unique=True)
    display_name = models.CharField(max_length=100)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IDLE)
    capabilities = models.JSONField(default=list, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    agent_version = models.CharField(max_length=40, default="dev4-agent/1.0")
    last_error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self):
        return self.display_name


class SystemEvent(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        BLOCKED = "BLOCKED", "Blocked"
        FAILED = "FAILED", "Failed"

    event_id = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=64, db_index=True)
    project_id = models.CharField(max_length=128, db_index=True)
    milestone_id = models.CharField(max_length=128, null=True, blank=True)
    occurred_at = models.DateTimeField()
    source = models.CharField(max_length=128)
    # Optional during contract migration: legacy producers can continue sending
    # the v1 envelope until the shared API contract is approved.
    schema_version = models.CharField(max_length=24, default="1.0")
    producer_id = models.CharField(max_length=128, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    payload_sha256 = models.CharField(max_length=64)
    correlation_id = models.CharField(max_length=128, null=True, blank=True)
    trace_id = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-received_at",)
        indexes = [models.Index(fields=("project_id", "received_at"), name="evt_project_received_idx")]


class EventOutbox(models.Model):
    """Durable hand-off from HTTP ingestion to the single local worker."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        RETRY = "RETRY", "Retry scheduled"
        PROCESSED = "PROCESSED", "Processed"
        QUARANTINED = "QUARANTINED", "Quarantined"

    event = models.OneToOneField(SystemEvent, on_delete=models.PROTECT, related_name="outbox")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=("status", "next_attempt_at"), name="outbox_due_idx")]


class WorkerLease(models.Model):
    """Database-backed singleton lease prevents accidentally starting pollers twice."""

    name = models.CharField(max_length=40, unique=True, default="event-worker")
    owner = models.CharField(max_length=64, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)


class ProjectReference(models.Model):
    """Local read model for real projects registered or imported into Dev 4."""

    class Provenance(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        IMPORTED = "IMPORTED", "Imported"
        GITHUB_API = "GITHUB_API", "GitHub API"
        HEDERA_MIRROR_NODE = "HEDERA_MIRROR_NODE", "Hedera Mirror Node"
        TEST_ONLY = "TEST_ONLY", "Test only"

    external_id = models.CharField(max_length=128, unique=True)
    title = models.CharField(max_length=180)
    status = models.CharField(max_length=40, default="UNKNOWN")
    description = models.CharField(max_length=1000, blank=True)
    provenance = models.CharField(max_length=24, choices=Provenance.choices)
    source_record_id = models.CharField(max_length=128, blank=True)
    created_by = models.CharField(max_length=128)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dev4_projects",
    )
    is_demo_only = models.BooleanField(default=False, db_index=True)
    import_batch = models.ForeignKey(
        "ProjectImportBatch", null=True, blank=True, on_delete=models.PROTECT,
        related_name="projects",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title", "external_id")


class FreelancerProfile(models.Model):
    class Role(models.TextChoices):
        FREELANCER = "FREELANCER", "Freelancer"
        CLIENT = "CLIENT", "Client"
        ADMIN = "ADMIN", "Admin"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="freelancer_profile")
    display_name = models.CharField(max_length=120)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.FREELANCER)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    github_login = models.CharField(max_length=39, blank=True)
    preferences = models.JSONField(default=dict, blank=True)
    is_demo_only = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_name", "id")


class ProjectMember(models.Model):
    project = models.ForeignKey(ProjectReference, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dev4_project_memberships")
    role = models.CharField(max_length=16, choices=(("FREELANCER", "Freelancer"), ("CLIENT", "Client")), default="FREELANCER")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="dev4_members_added")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("project", "user"), name="uniq_dev4_project_member")]


class ProjectAgreement(models.Model):
    class ApprovalStatus(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    project = models.OneToOneField(ProjectReference, on_delete=models.CASCADE, related_name="agreement")
    budget_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=12, blank=True)
    total_hours = models.PositiveIntegerField(null=True, blank=True)
    total_work_units = models.PositiveIntegerField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    target_deadline = models.DateField(null=True, blank=True)
    github_repository = models.CharField(max_length=200, blank=True)
    conditions = models.JSONField(default=list, blank=True)
    approval_status = models.CharField(max_length=12, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    provenance = models.CharField(max_length=24, choices=ProjectReference.Provenance.choices, default=ProjectReference.Provenance.MANUAL)
    plan_status = models.CharField(max_length=40, default="UNKNOWN")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProjectMilestone(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "PROPOSED", "Proposed"
        APPROVED = "APPROVED", "Approved"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"
        BLOCKED = "BLOCKED", "Blocked"
        UNKNOWN = "UNKNOWN", "Unknown"

    project = models.ForeignKey(ProjectReference, on_delete=models.CASCADE, related_name="milestones")
    milestone_id = models.CharField(max_length=128)
    title = models.CharField(max_length=180)
    description = models.CharField(max_length=1000, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    planned_work_units = models.PositiveIntegerField(null=True, blank=True)
    estimated_hours = models.PositiveIntegerField(null=True, blank=True)
    completed_work_units = models.PositiveIntegerField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED)
    provenance = models.CharField(max_length=24, choices=ProjectReference.Provenance.choices, default=ProjectReference.Provenance.MANUAL)
    source_event_id = models.CharField(max_length=128, blank=True)
    is_demo_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("order", "milestone_id")
        constraints = [models.UniqueConstraint(fields=("project", "milestone_id"), name="uniq_dev4_project_milestone")]


class EvidenceSubmission(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        UNKNOWN = "UNKNOWN", "Unknown"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"

    project = models.ForeignKey(ProjectReference, on_delete=models.CASCADE, related_name="evidence_submissions")
    milestone = models.ForeignKey(ProjectMilestone, null=True, blank=True, on_delete=models.SET_NULL, related_name="evidence_submissions")
    evidence_id = models.CharField(max_length=128)
    source = models.CharField(max_length=24, choices=(("MANUAL", "Manual"), ("GITHUB_API", "GitHub API"), ("TEST_ONLY", "Test only")))
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUBMITTED)
    repository = models.CharField(max_length=200, blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    proof_hash = models.CharField(max_length=64, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    source_refs = models.JSONField(default=list, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="dev4_evidence_submissions")
    source_event_id = models.CharField(max_length=128, blank=True)
    is_demo_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [models.UniqueConstraint(fields=("project", "evidence_id"), name="uniq_dev4_project_evidence")]


class ProjectApproval(models.Model):
    class Kind(models.TextChoices):
        AGREEMENT = "AGREEMENT", "Agreement"
        MILESTONE = "MILESTONE", "Milestone"
        RELEASE = "RELEASE", "Release"

    kind = models.CharField(max_length=12, choices=Kind.choices)
    project = models.ForeignKey(ProjectReference, on_delete=models.CASCADE, related_name="approvals")
    milestone = models.ForeignKey(ProjectMilestone, null=True, blank=True, on_delete=models.SET_NULL, related_name="approvals")
    decision = models.CharField(max_length=12, choices=(("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("PENDING", "Pending")))
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="dev4_project_approvals")
    reason = models.CharField(max_length=500, blank=True)
    provenance = models.CharField(max_length=24, choices=ProjectReference.Provenance.choices, default=ProjectReference.Provenance.MANUAL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class ProjectImportBatch(models.Model):
    class Status(models.TextChoices):
        PREVIEW = "PREVIEW", "Preview"
        IMPORTED = "IMPORTED", "Imported"

    batch_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    file_name = models.CharField(max_length=255, blank=True)
    file_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PREVIEW)
    accepted_rows = models.JSONField(default=list)
    rejected_rows = models.JSONField(default=list)
    actor_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    imported_at = models.DateTimeField(null=True, blank=True)


class ProjectAuditLog(models.Model):
    project = models.ForeignKey(ProjectReference, on_delete=models.PROTECT, related_name="audit_entries")
    batch = models.ForeignKey(ProjectImportBatch, null=True, blank=True, on_delete=models.PROTECT)
    actor_id = models.CharField(max_length=128)
    action = models.CharField(max_length=40)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("created_at", "id")


class AuditLog(models.Model):
    """Append-oriented timeline entry shared by orchestration and monitoring."""

    event = models.ForeignKey(SystemEvent, on_delete=models.PROTECT, related_name="audit_entries")
    project_id = models.CharField(max_length=128, db_index=True)
    trace_id = models.CharField(max_length=64, db_index=True)
    span_id = models.CharField(max_length=32, default=new_span_id)
    parent_span_id = models.CharField(max_length=32, null=True, blank=True)
    actor_type = models.CharField(max_length=24, default="SYSTEM")
    actor_id = models.CharField(max_length=128, blank=True)
    event_type = models.CharField(max_length=64)
    action = models.CharField(max_length=120)
    status = models.CharField(max_length=24)
    decision = models.CharField(max_length=16, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=("project_id", "created_at"), name="audit_project_time_idx")]


class AgentExecution(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        BLOCKED = "BLOCKED", "Blocked"
        RETRYABLE_FAILURE = "RETRYABLE_FAILURE", "Retryable failure"
        PERMANENT_FAILURE = "PERMANENT_FAILURE", "Permanent failure"

    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="executions")
    event = models.ForeignKey(SystemEvent, on_delete=models.CASCADE, related_name="executions")
    trace_id = models.CharField(max_length=64, db_index=True)
    span_id = models.CharField(max_length=32, default=new_span_id)
    parent_span_id = models.CharField(max_length=32, null=True, blank=True)
    agent_version = models.CharField(max_length=40, default="dev4-agent/1.0")
    idempotency_key = models.CharField(max_length=160, blank=True, default="")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED)
    reason_code = models.CharField(max_length=80, blank=True)
    source_refs = models.JSONField(default=list, blank=True)
    input_sha256 = models.CharField(max_length=64, blank=True)
    output = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("agent", "event"), name="uniq_agent_event_execution"),
        ]


class SettlementRecord(models.Model):
    """Read-only local projection of a settlement and its observed status."""

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        POLICY_PENDING = "POLICY_PENDING", "Policy pending"
        AUTHORIZED = "AUTHORIZED", "Authorized"
        POLICY_BLOCKED = "POLICY_BLOCKED", "Blocked by policy"
        SUBMITTED_BY_OWNER = "SUBMITTED_BY_OWNER", "Submitted by owner"
        OBSERVED_PENDING = "OBSERVED_PENDING", "Observed pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        FAILED = "FAILED", "Failed"
        UNKNOWN = "UNKNOWN", "Unknown"

    settlement_id = models.CharField(max_length=128, unique=True)
    project_id = models.CharField(max_length=128, db_index=True)
    trace_id = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.REQUESTED)
    transaction_id = models.CharField(max_length=128, blank=True)
    consensus_timestamp = models.CharField(max_length=64, blank=True)
    network = models.CharField(max_length=40, blank=True)
    source = models.CharField(max_length=128, blank=True)
    last_observed_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "settlement_id")


class SettlementTransition(models.Model):
    settlement = models.ForeignKey(SettlementRecord, on_delete=models.PROTECT, related_name="transitions")
    event = models.ForeignKey(SystemEvent, on_delete=models.PROTECT, related_name="settlement_transitions")
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24)
    source = models.CharField(max_length=128, blank=True)
    transaction_id = models.CharField(max_length=128, blank=True)
    consensus_timestamp = models.CharField(max_length=64, blank=True)
    reason_code = models.CharField(max_length=80, blank=True)
    observed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("observed_at", "id")
        constraints = [
            models.UniqueConstraint(fields=("settlement", "event"), name="uniq_settlement_event_transition"),
        ]


class SettlementMonitorAttempt(models.Model):
    class Outcome(models.TextChoices):
        OBSERVED = "OBSERVED", "Observation received"
        UNAVAILABLE = "UNAVAILABLE", "Source unavailable"
        INVALID = "INVALID", "Invalid observation"
        ERROR = "ERROR", "Source error"

    settlement = models.ForeignKey(SettlementRecord, on_delete=models.PROTECT, related_name="monitor_attempts")
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    source = models.CharField(max_length=128, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    observed_status = models.CharField(max_length=24, blank=True)
    transaction_id = models.CharField(max_length=128, blank=True)
    checked_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ("-checked_at", "-id")


class AgentAction(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="actions")
    event = models.ForeignKey(SystemEvent, on_delete=models.CASCADE, related_name="actions")
    project_id = models.CharField(max_length=128, db_index=True)
    trace_id = models.CharField(max_length=64, db_index=True)
    span_id = models.CharField(max_length=32)
    action_type = models.CharField(max_length=80)
    status = models.CharField(max_length=24)
    summary = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)


class AgentDecision(models.Model):
    class Decision(models.TextChoices):
        ALLOW = "ALLOW", "Allow"
        BLOCK = "BLOCK", "Block"
        HUMAN_REVIEW = "HUMAN_REVIEW", "Human review"
        PENDING = "PENDING", "Pending"

    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="decisions")
    event = models.ForeignKey(SystemEvent, on_delete=models.CASCADE, related_name="decisions")
    project_id = models.CharField(max_length=128, db_index=True)
    trace_id = models.CharField(max_length=64, db_index=True)
    decision = models.CharField(max_length=16, choices=Decision.choices)
    reason_code = models.CharField(max_length=80)
    reason = models.CharField(max_length=500)
    policy_version = models.CharField(max_length=40, blank=True)
    decided_by = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AgentTask(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="tasks")
    project_id = models.CharField(max_length=128, db_index=True)
    trace_id = models.CharField(max_length=64, db_index=True)
    task_type = models.CharField(max_length=80)
    status = models.CharField(max_length=16, default="PENDING")
    input_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AgentAlert(models.Model):
    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    alert_type = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(max_length=16, choices=Severity.choices)
    project_id = models.CharField(max_length=128, db_index=True)
    trace_id = models.CharField(max_length=64, blank=True, db_index=True)
    title = models.CharField(max_length=180)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)


class Notification(models.Model):
    alert = models.ForeignKey(AgentAlert, on_delete=models.CASCADE, related_name="notifications")
    channel = models.CharField(max_length=24, default="IN_APP")
    recipient = models.CharField(max_length=128, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DashboardMetric(models.Model):
    project_id = models.CharField(max_length=128, db_index=True)
    metric_key = models.CharField(max_length=80)
    value = models.FloatField()
    unit = models.CharField(max_length=24, blank=True)
    source = models.CharField(max_length=32, default="mock")
    measured_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ("-measured_at",)
        indexes = [models.Index(fields=("project_id", "metric_key", "measured_at"), name="metric_project_key_time_idx")]
