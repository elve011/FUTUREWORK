from django.db import models


class Project(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"

    # Renseigné après la création à partir de l'identifiant de base de données.
    project_id = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    client = models.CharField(max_length=200)
    worker = models.CharField(max_length=200)
    currency = models.CharField(max_length=4)
    total_units = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new and self.project_id is None:
            self.project_id = f"FW-{self.pk:03d}"
            type(self).objects.filter(pk=self.pk).update(
                project_id=self.project_id
            )

    def __str__(self):
        return f"{self.project_id or 'New project'} — {self.title}"


class WorkAgreement(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="agreements",
    )
    version = models.PositiveIntegerField(default=1)
    value = models.DecimalField(max_digits=14, decimal_places=2)
    conditions = models.TextField()
    deadline = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "version"],
                name="unique_agreement_version_per_project",
            ),
        ]

    def __str__(self):
        return f"{self.project.project_id} — Agreement v{self.version}"


class Milestone(models.Model):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"
        OVERDUE = "OVERDUE", "Overdue"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="milestones",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    units = models.PositiveIntegerField()
    deadline = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["deadline", "id"]

    def __str__(self):
        return f"{self.project.project_id} — {self.title}"


class ProjectPlanVersion(models.Model):
    """Immutable snapshot of a project's milestone and Work Unit plan."""

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="plan_versions",
    )
    version = models.PositiveIntegerField()
    agreement_version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "version"],
                name="unique_plan_version_per_project",
            ),
        ]


class WorkUnit(models.Model):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        ALLOCATED = "ALLOCATED", "Allocated"
        RELEASED = "RELEASED", "Released"

    milestone = models.ForeignKey(
        Milestone,
        on_delete=models.CASCADE,
        related_name="work_units",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    units = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.milestone.title} — {self.title}"


class Tokenization(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CREATED = "CREATED", "Created"
        FAILED = "FAILED", "Failed"

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="tokenization",
    )
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=20)
    total_supply = models.PositiveIntegerField()
    decimals = models.PositiveSmallIntegerField(default=0)
    token_id = models.CharField(max_length=100, blank=True)
    transaction_id = models.CharField(max_length=150, blank=True)
    hashscan_url = models.URLField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.project.project_id} — {self.name} ({self.symbol})"


class WalletConnection(models.Model):
    class Status(models.TextChoices):
        DISCONNECTED = "DISCONNECTED", "Disconnected"
        CONNECTED = "CONNECTED", "Connected"

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="wallet_connection",
    )
    provider = models.CharField(max_length=50, default="HashPack")
    account_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DISCONNECTED,
    )
    connected_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.project.project_id} — {self.provider}"


class HederaAccount(models.Model):
    class Role(models.TextChoices):
        CLIENT = "CLIENT", "Client"
        WORKER = "WORKER", "Worker"
        TREASURY = "TREASURY", "Treasury"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="hedera_accounts",
    )
    account_id = models.CharField(max_length=100)
    role = models.CharField(max_length=20, choices=Role.choices)
    token_associated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "account_id"],
                name="unique_hedera_account_per_project",
            ),
        ]

    def __str__(self):
        return f"{self.project.project_id} — {self.role}: {self.account_id}"
