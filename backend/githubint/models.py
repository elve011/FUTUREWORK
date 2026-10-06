from django.db import models


class GitHubRepository(models.Model):
    project_id = models.CharField(max_length=32, db_index=True)
    full_name = models.CharField(max_length=200, unique=True)       # owner/repo
    worker_github = models.CharField(max_length=100, blank=True)     # expected author login
    webhook_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def to_api(self):
        return {"projectId": self.project_id, "repoFullName": self.full_name, "workerGithub": self.worker_github,
                "webhookId": self.webhook_id}


class WebhookDelivery(models.Model):
    """Idempotency key = X-GitHub-Delivery (FR-E-02)."""
    delivery_id = models.CharField(max_length=64, unique=True)
    event_type = models.CharField(max_length=40)
    repository = models.CharField(max_length=200, blank=True)
    payload = models.JSONField()
    outcome = models.CharField(max_length=60, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)


class GitHubCommit(models.Model):
    repo = models.ForeignKey(GitHubRepository, on_delete=models.CASCADE, related_name="commits")
    sha = models.CharField(max_length=64)
    message = models.TextField(blank=True)
    author = models.CharField(max_length=100)
    branch = models.CharField(max_length=200, blank=True)
    committed_at = models.DateTimeField()
    files_changed = models.IntegerField(default=0)
    milestone_id = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["repo", "sha"], name="uniq_commit")]
        ordering = ["-committed_at"]

    def to_api(self):
        return {"sha": self.sha, "message": self.message, "author": self.author, "branch": self.branch,
                "committedAt": self.committed_at.isoformat(), "filesChanged": self.files_changed,
                "milestoneId": self.milestone_id, "repo": self.repo.full_name}


class PullRequest(models.Model):
    repo = models.ForeignKey(GitHubRepository, on_delete=models.CASCADE, related_name="pulls")
    number = models.IntegerField()
    title = models.CharField(max_length=300)
    author = models.CharField(max_length=100)
    branch = models.CharField(max_length=200, blank=True)
    merged = models.BooleanField(default=False)
    additions = models.IntegerField(null=True, blank=True)
    deletions = models.IntegerField(null=True, blank=True)
    labels = models.JSONField(default=list)
    merged_at = models.DateTimeField(null=True, blank=True)
    milestone_id = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["repo", "number"], name="uniq_pr")]
        ordering = ["-number"]

    def to_api(self):
        return {"number": self.number, "title": self.title, "author": self.author, "branch": self.branch,
                "merged": self.merged, "additions": self.additions, "deletions": self.deletions,
                "labels": self.labels, "milestoneId": self.milestone_id, "repo": self.repo.full_name}


class CodeReview(models.Model):
    repo = models.ForeignKey(GitHubRepository, on_delete=models.CASCADE, related_name="reviews")
    review_id = models.BigIntegerField()
    pr_number = models.IntegerField()
    reviewer = models.CharField(max_length=100)
    state = models.CharField(max_length=30)
    submitted_at = models.DateTimeField()
    milestone_id = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["repo", "review_id"], name="uniq_review")]
        ordering = ["-submitted_at"]

    def to_api(self):
        return {"reviewId": self.review_id, "prNumber": self.pr_number, "reviewer": self.reviewer,
                "state": self.state, "submittedAt": self.submitted_at.isoformat(),
                "milestoneId": self.milestone_id, "repo": self.repo.full_name}
