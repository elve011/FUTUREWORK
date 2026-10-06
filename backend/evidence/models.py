from datetime import timezone as dt_tz

from django.db import models


class Evidence(models.Model):
    class Status(models.TextChoices):
        COLLECTED = "COLLECTED"
        VERIFYING = "VERIFYING"
        VERIFIED = "VERIFIED"
        REJECTED = "REJECTED"
        ANCHORED = "ANCHORED"

    class Source(models.TextChoices):
        COMMIT = "COMMIT"
        PULL_REQUEST = "PULL_REQUEST"
        REVIEW = "REVIEW"
        MANUAL = "MANUAL"

    evidence_id = models.CharField(max_length=32, unique=True, null=True, blank=True, editable=False)  # EV-###
    project_id = models.CharField(max_length=32, db_index=True)     # shared ID, never a ForeignKey (rule R2)
    milestone_id = models.CharField(max_length=32, null=True, blank=True, db_index=True)
    milestone_source = models.CharField(max_length=16, blank=True, default="")
    source = models.CharField(max_length=16, choices=Source.choices)
    source_ref = models.CharField(max_length=200)
    author = models.CharField(max_length=100)
    title = models.CharField(max_length=300, blank=True)
    content_digest = models.CharField(max_length=80)
    occurred_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COLLECTED, db_index=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["project_id", "source", "source_ref"],
                                               name="uniq_evidence_source_ref")]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.evidence_id:
            self.evidence_id = f"EV-{self.pk:03d}"
            super().save(update_fields=["evidence_id"])

    @property
    def attached(self):
        return bool(self.milestone_id)

    def hashable(self) -> dict:
        """Stable fields only -> reproducible Proof Hash."""
        return {
            "projectId": self.project_id, "milestoneId": self.milestone_id, "source": self.source,
            "sourceRef": self.source_ref, "author": self.author, "contentDigest": self.content_digest,
            "occurredAt": self.occurred_at.astimezone(dt_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def latest_verification(self):
        return self.verifications.order_by("-id").first()

    def to_api(self, detail=False):
        v = self.latest_verification()
        proof = getattr(self, "proof", None)
        out = {
            "evidenceId": self.evidence_id, "projectId": self.project_id, "milestoneId": self.milestone_id,
            "milestoneSource": self.milestone_source or None, "attached": self.attached,
            "source": self.source, "sourceRef": self.source_ref, "author": self.author, "title": self.title,
            "status": self.status, "occurredAt": self.occurred_at.isoformat(),
            "complianceScore": v.score if v else None, "proofHash": proof.proof_hash if proof else None,
        }
        if detail:
            out["metadata"] = self.metadata
            out["verifications"] = [x.to_api() for x in self.verifications.order_by("id")]
        return out


class EvidenceVerification(models.Model):
    evidence = models.ForeignKey(Evidence, on_delete=models.CASCADE, related_name="verifications")
    score = models.PositiveSmallIntegerField()
    verdict = models.CharField(max_length=16)          # VERIFIED / REJECTED
    method = models.CharField(max_length=16)           # rules | rules+llm
    reasons = models.JSONField(default=list)           # explainable (FR-E-05)
    created_at = models.DateTimeField(auto_now_add=True)

    def to_api(self):
        return {"score": self.score, "verdict": self.verdict, "method": self.method, "reasons": self.reasons,
                "createdAt": self.created_at.isoformat()}


class EvidenceHash(models.Model):
    evidence = models.OneToOneField(Evidence, on_delete=models.CASCADE, related_name="proof")
    proof_hash = models.CharField(max_length=80, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EmittedEvent(models.Model):
    """Outbox: every event we publish is stored, so a Dev 4 outage never loses anything."""
    event_id = models.CharField(max_length=40, unique=True)
    type = models.CharField(max_length=40)
    project_id = models.CharField(max_length=32, db_index=True)
    envelope = models.JSONField()
    delivered = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
