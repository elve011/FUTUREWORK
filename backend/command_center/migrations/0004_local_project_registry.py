import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("command_center", "0003_durable_event_outbox")]

    operations = [
        migrations.CreateModel(
            name="ProjectImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("batch_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("file_name", models.CharField(blank=True, max_length=255)),
                ("file_sha256", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("PREVIEW", "Preview"), ("IMPORTED", "Imported")], default="PREVIEW", max_length=12)),
                ("accepted_rows", models.JSONField(default=list)),
                ("rejected_rows", models.JSONField(default=list)),
                ("actor_id", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("imported_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="ProjectReference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(max_length=128, unique=True)),
                ("title", models.CharField(max_length=180)),
                ("status", models.CharField(default="UNKNOWN", max_length=40)),
                ("description", models.CharField(blank=True, max_length=1000)),
                ("provenance", models.CharField(choices=[("MANUAL", "Manual"), ("IMPORTED", "Imported")], max_length=12)),
                ("source_record_id", models.CharField(blank=True, max_length=128)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("import_batch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="projects", to="command_center.projectimportbatch")),
            ],
            options={"ordering": ("title", "external_id")},
        ),
        migrations.CreateModel(
            name="ProjectAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("actor_id", models.CharField(max_length=128)),
                ("action", models.CharField(max_length=40)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("batch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="command_center.projectimportbatch")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="audit_entries", to="command_center.projectreference")),
            ],
            options={"ordering": ("created_at", "id")},
        ),
    ]
