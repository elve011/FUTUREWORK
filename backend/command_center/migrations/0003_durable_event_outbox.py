import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("command_center", "0002_auditlog")]

    operations = [
        migrations.AddField(
            model_name="systemevent", name="schema_version",
            field=models.CharField(default="1.0", max_length=24),
        ),
        migrations.AddField(
            model_name="systemevent", name="producer_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="systemevent", name="processed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="WorkerLease",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="event-worker", max_length=40, unique=True)),
                ("owner", models.CharField(blank=True, default="", max_length=64)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="EventOutbox",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("PROCESSING", "Processing"), ("RETRY", "Retry scheduled"), ("PROCESSED", "Processed"), ("QUARANTINED", "Quarantined")], default="PENDING", max_length=16)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("lease_until", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="outbox", to="command_center.systemevent")),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddIndex(
            model_name="eventoutbox",
            index=models.Index(fields=["status", "next_attempt_at"], name="outbox_due_idx"),
        ),
    ]
