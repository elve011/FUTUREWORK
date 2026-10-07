import json
import hashlib
import sqlite3
import tempfile
import time
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, override_settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError
from django.utils import timezone
from rest_framework.test import APIClient

from .adapters.mock import MockHederaAdapter, MockProjectAdapter, get_hedera_adapter
from .adapters.hedera import MirrorNodeObserver
from .models import Agent, AgentAction, AgentDecision, AgentExecution, AgentAlert, AuditLog, EventOutbox, ProjectAuditLog, ProjectImportBatch, ProjectReference, SystemEvent, WorkerLease


class Dev4ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @staticmethod
    def event(**overrides):
        data = {
            "event_id": "evt-001",
            "event_type": "MILESTONE_COMPLETED",
            "project_id": "FW-DEMO-001",
            "milestone_id": "milestone-02",
            "occurred_at": "2026-10-01T10:00:00Z",
            "source": "evidence-service",
            "payload": {"units_completed": 10},
            "correlation_id": "upstream-001",
        }
        data.update(overrides)
        return data

    def test_health_endpoint_is_standalone(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["service"], "futurework-dev4")

    def test_agent_registry_returns_the_four_spec_agents(self):
        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 4)
        self.assertEqual(
            {agent["id"] for agent in response.data["results"]},
            {"planner", "evidence", "risk", "settlement"},
        )
        self.assertEqual(Agent.objects.count(), 4)

    def test_ingestion_creates_trace_and_persists_event(self):
        response = self.client.post("/api/events/ingest", self.event(), format="json")
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.data["trace_id"].startswith("FW-TRACE-"))
        self.assertEqual(SystemEvent.objects.count(), 1)
        self.assertEqual(response.data["processing_status"], EventOutbox.Status.PENDING)
        self.assertEqual(SystemEvent.objects.get().status, SystemEvent.Status.RECEIVED)
        self.assertEqual(EventOutbox.objects.count(), 1)
        self.assertEqual(AgentExecution.objects.count(), 0)
        call_command("process_events", "--once", verbosity=0)
        self.assertEqual(SystemEvent.objects.get().status, SystemEvent.Status.COMPLETED)
        self.assertIsNotNone(SystemEvent.objects.get().processed_at)
        self.assertEqual(AgentExecution.objects.count(), 1)
        self.assertEqual(AgentAction.objects.get().action_type, "EXECUTE_EVENT")
        self.assertEqual(AgentDecision.objects.get().decision, "PENDING")
        self.assertEqual(AuditLog.objects.count(), 3)
        self.assertTrue(all(row.trace_id == response.data["trace_id"] for row in AuditLog.objects.all()))

    def test_repeated_identical_event_is_idempotent(self):
        first = self.client.post("/api/events/ingest", self.event(), format="json")
        second = self.client.post("/api/events/ingest", self.event(), format="json")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["duplicate"])
        self.assertEqual(first.data["trace_id"], second.data["trace_id"])
        self.assertEqual(SystemEvent.objects.count(), 1)
        self.assertEqual(EventOutbox.objects.count(), 1)
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_settlement_request_requires_human_review_and_is_not_released(self):
        response = self.client.post(
            "/api/events/ingest",
            self.event(event_id="evt-settlement", event_type="SETTLEMENT_REQUESTED", payload={"amount": 5}),
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        call_command("process_events", "--once", verbosity=0)
        self.assertEqual(SystemEvent.objects.get().status, SystemEvent.Status.BLOCKED)
        self.assertEqual(AgentDecision.objects.get().reason_code, "POLICY_EVIDENCE_REQUIRED")

    def test_policy_decision_event_is_routed_to_risk_and_audited(self):
        response = self.client.post(
            "/api/events/ingest",
            self.event(event_id="evt-policy", event_type="POLICY_DECIDED", payload={"decision": "ALLOW", "reason_code": "OK"}),
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        call_command("process_events", "--once", verbosity=0)
        decision = AgentDecision.objects.get()
        self.assertEqual(decision.decision, "ALLOW")
        self.assertEqual(decision.agent.key, "risk")

    def test_alert_event_creates_project_alert_during_ingestion(self):
        response = self.client.post(
            "/api/events/ingest",
            self.event(event_id="evt-risk", event_type="HIGH_RISK", payload={"risk_level": "HIGH"}),
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        call_command("process_events", "--once", verbosity=0)
        self.assertEqual(AgentAlert.objects.get().alert_type, "HIGH_RISK")

    def test_all_six_required_alert_fixtures_are_created_within_ten_seconds(self):
        alert_events = (
            "MILESTONE_DELAYED",
            "EVIDENCE_MISSING",
            "HIGH_RISK",
            "TRANSACTION_FAILED",
            "AGENT_BLOCKED",
            "HEDERA_ERROR",
        )
        started = time.perf_counter()
        for index, event_type in enumerate(alert_events):
            with self.subTest(event_type=event_type):
                response = self.client.post(
                    "/api/events/ingest",
                    self.event(event_id=f"evt-alert-{index}", event_type=event_type),
                    format="json",
                )
                self.assertEqual(response.status_code, 202)
        call_command("process_events", "--once", verbosity=0)
        for event_type in alert_events:
            self.assertTrue(AgentAlert.objects.filter(alert_type=event_type).exists())
        self.assertLess(time.perf_counter() - started, 10)

    def test_four_local_demo_event_types_route_to_expected_agents(self):
        catalog_path = Path(__file__).parent / "fixtures" / "demo_event_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for event in catalog["events"]:
            with self.subTest(event_type=event["event_type"]):
                expected_agent = event.pop("expected_agent")
                response = self.client.post("/api/events/ingest", event, format="json")
                self.assertEqual(response.status_code, 202)
                event["_expected_agent"] = expected_agent
        call_command("process_events", "--once", verbosity=0)
        for event in catalog["events"]:
            self.assertTrue(AgentAction.objects.filter(event__event_id=event["event_id"], agent__key=event["_expected_agent"]).exists())

    def test_reused_event_id_with_different_payload_conflicts(self):
        self.client.post("/api/events/ingest", self.event(), format="json")
        response = self.client.post(
            "/api/events/ingest",
            self.event(payload={"units_completed": 99}),
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"], "EVENT_ID_CONFLICT")
        self.assertEqual(SystemEvent.objects.count(), 1)

    def test_reused_event_id_with_different_source_conflicts(self):
        self.client.post("/api/events/ingest", self.event(), format="json")
        response = self.client.post(
            "/api/events/ingest",
            self.event(source="different-service"),
            format="json",
        )
        self.assertEqual(response.status_code, 409)

    def test_missing_required_field_is_rejected(self):
        data = self.event()
        del data["project_id"]
        response = self.client.post("/api/events/ingest", data, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SystemEvent.objects.count(), 0)

    def test_unknown_envelope_field_is_rejected(self):
        data = self.event(trace_id="caller-controlled")
        response = self.client.post("/api/events/ingest", data, format="json")
        self.assertEqual(response.status_code, 400)

    def test_secret_like_payload_fields_are_redacted_at_rest(self):
        self.client.post(
            "/api/events/ingest",
            self.event(payload={"metadata": {"api_token": "do-not-store", "safe": "visible"}}),
            format="json",
        )
        stored = SystemEvent.objects.get().payload
        self.assertEqual(stored["metadata"]["api_token"], "[REDACTED]")
        self.assertEqual(stored["metadata"]["safe"], "visible")
        self.assertNotIn("do-not-store", json.dumps(stored))

    @override_settings(FW_INGEST_API_KEYS={"dev2": "test-secret"})
    def test_producer_api_key_is_required_and_source_is_not_identity(self):
        denied = self.client.post("/api/events/ingest", self.event(), format="json")
        self.assertEqual(denied.status_code, 401)
        accepted = self.client.post(
            "/api/events/ingest", self.event(producer_id="dev2"), format="json",
            HTTP_X_PRODUCER_ID="dev2", HTTP_X_API_KEY="test-secret",
        )
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(SystemEvent.objects.get().producer_id, "dev2")

    @override_settings(FW_INGEST_AUTH_REQUIRED=True, FW_INGEST_API_KEYS={})
    def test_production_ingestion_fails_closed_without_auth_configuration(self):
        response = self.client.post("/api/events/ingest", self.event(), format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"], "INGEST_AUTH_NOT_CONFIGURED")
        self.assertEqual(SystemEvent.objects.count(), 0)

    def test_provisional_local_event_profiles_validate_without_upstream_services(self):
        local_profiles = (
            ("WORK_CREATED", {"work_id": "work-01", "title": "Real source work"}),
            ("EVIDENCE_SUBMITTED", {"evidence_id": "evidence-01", "work_id": "work-01", "content_sha256": "a" * 64}),
            ("POLICY_DECIDED", {"decision_id": "decision-01", "decision": "HUMAN_REVIEW", "reason_code": "NEEDS_REVIEW", "policy_version": "policy-1"}),
            ("SETTLEMENT_UPDATED", {"settlement_id": "settlement-01", "status": "SUBMITTED", "transaction_id": "0.0.123@1.2"}),
        )
        for index, (event_type, payload) in enumerate(local_profiles):
            with self.subTest(event_type=event_type):
                response = self.client.post(
                    "/api/events/ingest",
                    self.event(event_id=f"evt-local-contract-{index}", event_type=event_type, schema_version="dev4-local/1.0", payload=payload),
                    format="json",
                )
                self.assertEqual(response.status_code, 202)

    def test_provisional_local_contract_rejects_invalid_payload_but_legacy_stays_compatible(self):
        invalid = self.client.post(
            "/api/events/ingest",
            self.event(event_id="evt-local-invalid", event_type="EVIDENCE_SUBMITTED", schema_version="dev4-local/1.0", payload={"evidence_id": "e-1", "work_id": "w-1", "content_sha256": "bad"}),
            format="json",
        )
        legacy = self.client.post(
            "/api/events/ingest", self.event(event_id="evt-legacy-payload", event_type="EVIDENCE_SUBMITTED", payload={"evidence_id": "example"}), format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(legacy.status_code, 202)

    def test_envelope_rejects_oversized_and_unknown_fields(self):
        too_large = self.client.post("/api/events/ingest", self.event(payload={"blob": "x" * (256 * 1024)}), format="json")
        self.assertEqual(too_large.status_code, 400)
        self.assertEqual(SystemEvent.objects.count(), 0)

    def test_worker_retries_then_quarantines_and_audits_without_leaking_exception(self):
        self.client.post("/api/events/ingest", self.event(), format="json")
        with patch("command_center.management.commands.process_events.process_event", side_effect=RuntimeError("sensitive data")):
            call_command("process_events", "--once", "--max-attempts", "1", verbosity=0)
        outbox = EventOutbox.objects.get()
        self.assertEqual(outbox.status, EventOutbox.Status.QUARANTINED)
        self.assertEqual(outbox.last_error_code, "WORKFLOW_ERROR")
        self.assertEqual(AgentExecution.objects.get().status, AgentExecution.Status.PERMANENT_FAILURE)
        self.assertEqual(AgentExecution.objects.get().reason_code, "WORKFLOW_ERROR")
        self.assertNotIn("sensitive data", json.dumps(list(AuditLog.objects.values("details"))))
        self.assertTrue(AuditLog.objects.filter(action="OUTBOX_QUARANTINED").exists())

    def test_expired_worker_lease_can_be_reclaimed(self):
        WorkerLease.objects.create(name="event-worker", owner="dead-worker", expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post("/api/events/ingest", self.event(), format="json")
        self.assertEqual(response.status_code, 202)
        call_command("process_events", "--once", verbosity=0)
        self.assertEqual(EventOutbox.objects.get().status, EventOutbox.Status.PROCESSED)

    def test_worker_recovers_expired_processing_claim_after_restart(self):
        self.client.post("/api/events/ingest", self.event(), format="json")
        outbox = EventOutbox.objects.get()
        outbox.status = EventOutbox.Status.PROCESSING
        outbox.lease_until = timezone.now() - timedelta(seconds=1)
        outbox.save(update_fields=("status", "lease_until", "updated_at"))
        call_command("process_events", "--once", verbosity=0)
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EventOutbox.Status.PROCESSED)
        self.assertEqual(outbox.attempt_count, 1)
        self.assertEqual(AgentAction.objects.filter(event__event_id=outbox.event.event_id).count(), 1)

    def test_retry_after_transient_failure_completes_once_after_due_time(self):
        self.client.post("/api/events/ingest", self.event(), format="json")
        with patch("command_center.management.commands.process_events.process_event", side_effect=RuntimeError("transient")):
            call_command("process_events", "--once", verbosity=0)
        outbox = EventOutbox.objects.get()
        self.assertEqual(outbox.status, EventOutbox.Status.RETRY)
        self.assertEqual(AgentExecution.objects.get().status, AgentExecution.Status.RETRYABLE_FAILURE)
        outbox.next_attempt_at = timezone.now() - timedelta(seconds=1)
        outbox.save(update_fields=("next_attempt_at",))
        call_command("process_events", "--once", verbosity=0)
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EventOutbox.Status.PROCESSED)
        self.assertEqual(outbox.attempt_count, 2)
        self.assertEqual(AgentAction.objects.filter(event=outbox.event).count(), 1)
        self.assertEqual(AgentExecution.objects.get().status, AgentExecution.Status.COMPLETED)

    def test_ingestion_collision_is_rejected_without_second_outbox(self):
        self.client.post("/api/events/ingest", self.event(), format="json")
        conflict = self.client.post("/api/events/ingest", self.event(source="other-source"), format="json")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(EventOutbox.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="EVENT_ID_CONFLICT").exists())

    def test_sqlite_busy_returns_retryable_response_and_rolls_back_event_and_outbox(self):
        with patch("command_center.views.EventOutbox.objects.create", side_effect=OperationalError("database is locked")):
            response = self.client.post("/api/events/ingest", self.event(), format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "1")
        self.assertEqual(SystemEvent.objects.count(), 0)
        self.assertEqual(EventOutbox.objects.count(), 0)

    def test_late_event_is_retained_with_source_time_and_ingested_without_reordering(self):
        old = self.client.post(
            "/api/events/ingest",
            self.event(event_id="evt-late", occurred_at="2020-01-01T00:00:00Z"),
            format="json",
        )
        newer = self.client.post(
            "/api/events/ingest",
            self.event(event_id="evt-newer", occurred_at="2026-10-02T00:00:00Z"),
            format="json",
        )
        self.assertEqual((old.status_code, newer.status_code), (202, 202))
        self.assertLess(SystemEvent.objects.get(event_id="evt-late").occurred_at, SystemEvent.objects.get(event_id="evt-newer").occurred_at)
        call_command("process_events", "--once", verbosity=0)
        self.assertEqual(EventOutbox.objects.filter(status=EventOutbox.Status.PROCESSED).count(), 2)



class SQLiteOperationsTests(TransactionTestCase):
    def test_sqlite_backup_is_integrity_checked_and_restorable(self):
        APIClient().post("/api/events/ingest", Dev4ApiTests.event(), format="json")
        with tempfile.TemporaryDirectory() as directory:
            backup_path = Path(directory) / "dev4-backup.sqlite3"
            restored_path = Path(directory) / "restored-test-db.sqlite3"
            call_command("backup_sqlite", str(backup_path), verbosity=0)
            call_command("restore_sqlite", str(backup_path), str(restored_path), verbosity=0)
            restored = sqlite3.connect(restored_path)
            try:
                self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(restored.execute("SELECT COUNT(*) FROM command_center_systemevent").fetchone()[0], 1)
                self.assertEqual(restored.execute("SELECT COUNT(*) FROM command_center_eventoutbox").fetchone()[0], 1)
            finally:
                restored.close()
            with self.assertRaises(CommandError):
                call_command("restore_sqlite", str(backup_path), str(restored_path), verbosity=0)


class MockAdapterTests(TestCase):
    def test_project_fixture_has_documented_dashboard_counts(self):
        snapshot = MockProjectAdapter().get_project_snapshot("FW-DEMO-001")
        self.assertEqual(snapshot["units"], {"completed": 64, "total": 100})
        self.assertEqual(snapshot["milestones"], {"completed": 3, "total": 5})
        self.assertEqual(snapshot["source"], "mock")

    def test_mirror_node_fixture_covers_required_hedera_object_types(self):
        activity = MockHederaAdapter().get_activity("FW-DEMO-001")
        self.assertEqual(
            {item["kind"] for item in activity},
            {"HCS_MESSAGE", "HTS_TRANSFER", "CONTRACT_CALL", "SCHEDULED_TRANSACTION"},
        )
        self.assertTrue(all(item["hashscan_url"].startswith("https://hashscan.io/testnet/") for item in activity))

    def test_unknown_project_does_not_fall_back_to_another_fixture(self):
        with self.assertRaises(KeyError):
            MockProjectAdapter().get_project_snapshot("OTHER-PROJECT")

    def test_live_mode_uses_read_only_mirror_node_observer_not_mock_fixture(self):
        self.assertIsInstance(get_hedera_adapter("live"), MirrorNodeObserver)


@override_settings(FW_OPERATOR_API_KEYS={"emna": "operator-secret", "other": "other-secret"})
class ProjectRegistryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator_headers = {"HTTP_X_OPERATOR_ID": "emna", "HTTP_X_OPERATOR_KEY": "operator-secret"}

    @staticmethod
    def project(**overrides):
        return {
            "external_id": "FW-REAL-001",
            "title": "Projet client réellement enregistré",
            "status": "ACTIVE",
            "description": "Données fournies par l'opérateur autorisé.",
            "source_record_id": "client-record-77",
            **overrides,
        }

    def test_empty_registry_is_empty_and_contains_no_demo_project(self):
        response = self.client.get("/api/projects", **self.operator_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_manual_project_requires_operator_and_records_provenance_audit(self):
        denied = self.client.post("/api/projects", self.project(), format="json")
        self.assertEqual(denied.status_code, 401)
        created = self.client.post("/api/projects", self.project(), format="json", **self.operator_headers)
        self.assertEqual(created.status_code, 201)
        project = ProjectReference.objects.get()
        self.assertEqual(project.provenance, ProjectReference.Provenance.MANUAL)
        self.assertEqual(project.created_by, "emna")
        self.assertEqual(ProjectAuditLog.objects.get().action, "PROJECT_CREATED_MANUAL")

    def test_local_dashboard_preserves_unknown_metrics_and_never_substitutes_demo_data(self):
        self.client.post("/api/projects", self.project(), format="json", **self.operator_headers)
        response = self.client.get("/api/projects/FW-REAL-001/dashboard", **self.operator_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["project"]["source"], "local-registry")
        self.assertIsNone(response.data["project"]["progress_percent"])
        self.assertEqual(response.data["project"]["risk"]["level"], "UNKNOWN")
        self.assertEqual(response.data["hedera_activity"], [])
        self.assertEqual(response.data["sources"]["hedera"], "not-configured")
        self.assertEqual(response.data["event_queue"]["pending"], 0)
        activity = self.client.get("/api/projects/FW-REAL-001/activity", **self.operator_headers)
        audit_row = next(row for row in activity.data["results"] if row["kind"] == "PROJECT_AUDIT")
        self.assertEqual(audit_row["actor_id"], "emna")
        self.assertEqual(audit_row["status"], "PROJECT_CREATED_MANUAL")

    def test_real_project_dashboard_shows_pending_then_processed_event_queue(self):
        self.client.post("/api/projects", self.project(), format="json", **self.operator_headers)
        event = Dev4ApiTests.event(event_id="evt-local-project-flow", project_id="FW-REAL-001")
        ingested = self.client.post("/api/events/ingest", event, format="json")
        self.assertEqual(ingested.status_code, 202)
        pending = self.client.get("/api/projects/FW-REAL-001/dashboard", **self.operator_headers)
        self.assertEqual(pending.data["event_queue"]["pending"], 1)
        activity = self.client.get("/api/projects/FW-REAL-001/activity", **self.operator_headers)
        event_row = next(row for row in activity.data["results"] if row["kind"] == "EVENT" and row["event_id"] == event["event_id"])
        self.assertEqual(event_row["processing_status"], "PENDING")
        call_command("process_events", "--once", verbosity=0)
        processed = self.client.get("/api/projects/FW-REAL-001/dashboard", **self.operator_headers)
        self.assertEqual(processed.data["event_queue"]["processed"], 1)
        activity = self.client.get("/api/projects/FW-REAL-001/activity", **self.operator_headers)
        event_row = next(row for row in activity.data["results"] if row["kind"] == "EVENT" and row["event_id"] == event["event_id"])
        self.assertEqual(event_row["processing_status"], "PROCESSED")

    def test_duplicate_manual_id_is_conflict_without_overwrite(self):
        self.client.post("/api/projects", self.project(), format="json", **self.operator_headers)
        duplicate = self.client.post("/api/projects", self.project(title="Autre titre"), format="json", **self.operator_headers)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(ProjectReference.objects.get().title, self.project()["title"])

    def test_import_preview_keeps_rows_out_of_live_registry_until_commit(self):
        rows = [self.project(), self.project(external_id="FW-REAL-002"), self.project(external_id="FW-REAL-001"), {"external_id": "FW-INCOMPLETE"}]
        preview = self.client.post("/api/projects/import/preview", {"projects": rows}, format="json", **self.operator_headers)
        self.assertEqual(preview.status_code, 201)
        self.assertEqual(preview.data["accepted_count"], 2)
        self.assertEqual(preview.data["rejected_count"], 2)
        self.assertIn("title", preview.data["rejected"][1]["errors"])
        self.assertEqual(ProjectReference.objects.count(), 0)
        batch = ProjectImportBatch.objects.get()
        self.assertEqual(batch.status, ProjectImportBatch.Status.PREVIEW)
        self.assertEqual(len(batch.file_sha256), 64)
        committed = self.client.post(preview.data["commit_url"], {}, format="json", **self.operator_headers)
        self.assertEqual(committed.status_code, 200)
        self.assertEqual(committed.data["imported_count"], 2)
        self.assertEqual(ProjectReference.objects.filter(provenance="IMPORTED", created_by="emna").count(), 2)
        self.assertEqual(ProjectAuditLog.objects.filter(action="PROJECT_IMPORTED").count(), 2)
        self.assertEqual(ProjectReference.objects.filter(import_batch=batch).count(), 2)

    def test_import_commit_is_actor_bound_and_cannot_be_repeated(self):
        preview = self.client.post("/api/projects/import/preview", {"projects": [self.project()]}, format="json", **self.operator_headers)
        commit_path = f"/api/projects/imports/{preview.data['batch_id']}/commit"
        wrong_actor = self.client.post(
            commit_path, {}, format="json", HTTP_X_OPERATOR_ID="other", HTTP_X_OPERATOR_KEY="other-secret",
        )
        self.assertEqual(wrong_actor.status_code, 403)
        first = self.client.post(commit_path, {}, format="json", **self.operator_headers)
        second = self.client.post(commit_path, {}, format="json", **self.operator_headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(ProjectReference.objects.count(), 1)

    def test_csv_import_uses_raw_file_hash_and_commits_provenance(self):
        content = b"external_id,title,status,description,source_record_id\nFW-CSV-01,Client CSV,ACTIVE,Imported,crm-77\n"
        upload = SimpleUploadedFile("clients.csv", content, content_type="text/csv")
        preview = self.client.post("/api/projects/import/preview", {"file": upload}, format="multipart", **self.operator_headers)
        self.assertEqual(preview.status_code, 201)
        self.assertEqual(preview.data["file_sha256"], hashlib.sha256(content).hexdigest())
        self.client.post(preview.data["commit_url"], {}, format="json", **self.operator_headers)
        project = ProjectReference.objects.get()
        self.assertEqual(project.external_id, "FW-CSV-01")
        self.assertEqual(project.provenance, ProjectReference.Provenance.IMPORTED)


@override_settings(FW_OPERATOR_API_KEYS={"test-operator": "test-operator-secret"})
class Dev4ReadApiTests(TestCase):
    project_id = "FW-DEMO-001"

    def setUp(self):
        self.client = APIClient()
        self.operator_headers = {"HTTP_X_OPERATOR_ID": "test-operator", "HTTP_X_OPERATOR_KEY": "test-operator-secret"}

    def test_dashboard_aggregates_project_and_agent_fixtures(self):
        response = self.client.get(f"/api/projects/{self.project_id}/dashboard", **self.operator_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["project"]["units"], {"completed": 64, "total": 100})
        self.assertEqual(len(response.data["agents"]), 4)
        self.assertEqual(response.data["sources"]["project"], "mock")
        self.assertEqual(len(response.data["hedera_activity"]), 4)

    @override_settings(FW_MODE_HEDERA="live")
    def test_dashboard_does_not_substitute_fixture_when_live_hedera_has_no_project_references(self):
        response = self.client.get(f"/api/projects/{self.project_id}/dashboard", **self.operator_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["hedera_activity"], [])
        self.assertEqual(response.data["sources"]["hedera"], "not-configured")
        self.assertEqual(response.data["source_status"]["hedera"], "no_observations")

    def test_project_metrics_include_project_fixture_counts(self):
        response = self.client.get(f"/api/projects/{self.project_id}/metrics", **self.operator_headers)
        self.assertEqual(response.status_code, 200)
        metrics = {metric["key"]: metric["value"] for metric in response.data["metrics"]}
        self.assertEqual(metrics["progress_percent"], 64)
        self.assertEqual(metrics["milestones_completed"], 3)

    def test_hedera_endpoints_expose_all_mock_fixture_kinds(self):
        activity = self.client.get(f"/api/projects/{self.project_id}/hedera/activity", **self.operator_headers)
        transactions = self.client.get(f"/api/projects/{self.project_id}/hedera/transactions", **self.operator_headers)
        self.assertEqual(activity.status_code, 200)
        self.assertEqual(transactions.status_code, 200)
        self.assertEqual(activity.data["count"], 4)
        self.assertEqual(transactions.data["count"], 2)
        self.assertTrue(all(row["source"] == "mock-mirror-node-fixture" for row in activity.data["results"]))

    def test_unknown_project_is_not_silently_mapped_to_demo_fixture(self):
        response = self.client.get("/api/projects/NO-SUCH-PROJECT/dashboard", **self.operator_headers)
        self.assertEqual(response.status_code, 404)

    @override_settings(FW_MODE_PROJECT="live")
    def test_unimplemented_live_project_source_returns_503(self):
        response = self.client.get(f"/api/projects/{self.project_id}/dashboard", **self.operator_headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"], "SOURCE_MODE_UNAVAILABLE")

    def test_openapi_endpoint_is_available(self):
        response = self.client.get("/api/openapi")
        self.assertEqual(response.status_code, 200)
        self.assertIn("paths", response.data)
