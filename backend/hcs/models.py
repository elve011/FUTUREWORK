from django.db import models


class HCSTopic(models.Model):
    project_id = models.CharField(max_length=32, unique=True)   # one topic per project (FR-E-07)
    topic_id = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    def to_api(self):
        return {"projectId": self.project_id, "topicId": self.topic_id,
                "hashscanUrl": f"https://hashscan.io/testnet/topic/{self.topic_id}"}


class HCSEvent(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"        # submit failed, will be retried
        SUBMITTED = "SUBMITTED"  # accepted by Hedera, Mirror readback pending
        CONFIRMED = "CONFIRMED"  # read back from Mirror Node, hash identical
        FAILED = "FAILED"        # readback mismatch

    topic = models.ForeignKey(HCSTopic, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=40)
    evidence_id = models.CharField(max_length=32, blank=True, db_index=True)
    milestone_id = models.CharField(max_length=32, blank=True)
    proof_hash = models.CharField(max_length=80)
    message = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    sequence_number = models.BigIntegerField(null=True, blank=True)
    consensus_timestamp = models.CharField(max_length=32, blank=True)
    transaction_id = models.CharField(max_length=64, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    readback_ok = models.BooleanField(null=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # never two HCS messages for the same hash (FR-E-11)
        constraints = [models.UniqueConstraint(fields=["topic", "event_type", "proof_hash"], name="uniq_hcs_hash")]
        ordering = ["sequence_number", "id"]

    def to_api(self):
        return {
            "id": self.pk, "eventType": self.event_type, "evidenceId": self.evidence_id,
            "milestoneId": self.milestone_id, "projectId": self.topic.project_id, "proofHash": self.proof_hash,
            "status": self.status, "topicId": self.topic.topic_id, "sequenceNumber": self.sequence_number,
            "consensusTimestamp": self.consensus_timestamp or None, "transactionId": self.transaction_id or None,
            "readbackOk": self.readback_ok, "attempts": self.attempts, "lastError": self.last_error or None,
            "hashscanUrl": f"https://hashscan.io/testnet/topic/{self.topic.topic_id}",
            "transactionUrl": self.transaction_url(),
        }

    def transaction_url(self):
        # 0.0.1234@1760000000.123456789 -> 0.0.1234-1760000000-123456789 (HashScan format)
        if not self.transaction_id or "@" not in self.transaction_id:
            return None
        acct, ts = self.transaction_id.split("@")
        return f"https://hashscan.io/testnet/transaction/{acct}-{ts.replace('.', '-')}"
