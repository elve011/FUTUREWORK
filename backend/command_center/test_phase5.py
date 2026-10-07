import json
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .adapters.evidence import EvidenceSourceError, GitHubEvidenceAdapter
from .models import Agent, AgentAction, AgentAlert, AgentDecision, AgentExecution, EventOutbox, SettlementMonitorAttempt, SettlementRecord, SystemEvent, WorkerLease


LOCAL = "dev4-local/1.0"


@override_settings(FW_OPERATOR_API_KEYS={"test-operator": "test-operator-secret"})
class Phase5AgentAndSettlementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator_headers = {"HTTP_X_OPERATOR_ID": "test-operator", "HTTP_X_OPERATOR_KEY": "test-operator-secret"}

    def ingest(self, event_id, event_type, payload, *, schema=LOCAL, project_id="LOCAL-PROJECT-01", correlation_id=None):
        return self.client.post("/api/events/ingest", {
            "schema_version": schema,
            "event_id": event_id,
            "event_type": event_type,
            "project_id": project_id,
            "occurred_at": "2026-10-03T10:00:00Z",
            "source": "dev4-local-test",
            "payload": payload,
            "correlation_id": correlation_id,
        }, format="json")

    def process_one(self):
        call_command("process_events", "--once", verbosity=0)

    def test_planner_returns_versioned_projection_without_inventing_progress(self):
        response = self.ingest("phase5-work-1", "WORK_CREATED", {"work_id": "work-9", "title": "Build local dashboard"})
        self.assertEqual(response.status_code, 202)
        self.process_one()
        execution = AgentExecution.objects.get(event__event_id="phase5-work-1")
        self.assertEqual(execution.agent_version, "planner/1.1-local")
        self.assertEqual(execution.status, AgentExecution.Status.COMPLETED)
        self.assertEqual(execution.output["work_id"], "work-9")
        self.assertIsNone(execution.output["progress"])
        self.assertEqual(execution.source_refs, ["phase5-work-1"])
        self.assertTrue(execution.idempotency_key)
        self.assertEqual(AgentAction.objects.filter(event=execution.event).count(), 1)
        history = self.client.get("/api/agents/planner/history", **self.operator_headers)
        self.assertEqual(history.status_code, 200)
        execution_entry = next(row for row in history.data["results"] if row["kind"] == "EXECUTION")
        self.assertEqual(execution_entry["agent_version"], "planner/1.1-local")
        self.assertIsNone(execution_entry["output"]["progress"])
        self.assertGreaterEqual(execution_entry["duration_ms"], 0)

    def _workflow_fixture(self):
        path = Path(__file__).parent / "fixtures" / "phase1_5_workflows.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _run_fixture_scenario(self, scenario):
        fixture = self._workflow_fixture()
        self.assertEqual(fixture["provenance"], "TEST_ONLY_SYNTHETIC_NOT_GITHUB_NOT_HEDERA")
        data = fixture["scenarios"][scenario]
        for row in data["events"]:
            response = self.ingest(
                row["event_id"], row["event_type"], row["payload"],
                project_id=data["project_id"], correlation_id=data["correlation_id"],
            )
            self.assertEqual(response.status_code, 202, response.data)
            self.process_one()
        return data

    def test_phase1_to_5_synthetic_allow_flow_runs_all_four_agents_and_finality_monitor(self):
        data = self._run_fixture_scenario("allow")
        planner = AgentExecution.objects.get(event__event_id="fixture-allow-engagement")
        self.assertEqual(planner.agent_version, "planner/1.1-local")
        self.assertEqual(planner.output["plan_status"], "PROPOSED_REQUIRES_HUMAN_APPROVAL")
        self.assertEqual(planner.output["allocated_work_units"], 100)
        self.assertEqual(planner.output["allocated_hours"], 100)
        self.assertEqual(planner.output["deadline_status"], "SCHEDULED")
        self.assertEqual([row["work_units"] for row in planner.output["milestones"]], [10, 30, 30, 15, 15])
        self.assertEqual(planner.output["milestones"][-1]["target_date"], "2026-11-30")
        self.assertEqual(planner.output["past_due_milestones_at_event_time"], [])

        evidence = AgentExecution.objects.get(event__event_id="fixture-allow-evidence")
        self.assertEqual(evidence.output["verdict"], "VERIFIED")
        self.assertEqual(evidence.output["score"], 100)
        self.assertTrue(evidence.output["synthetic_data"])
        self.assertEqual(len(evidence.output["proof_hash"]), 64)

        decision = AgentExecution.objects.get(event__event_id="fixture-allow-policy")
        self.assertEqual(decision.output["decision"], "ALLOW")
        self.assertEqual(decision.output["decision_scope"], "LOCAL_SIMULATION_NO_TRANSFER")
        audit_decision = AgentDecision.objects.get(event=decision.event)
        self.assertEqual(audit_decision.policy_version, "dev4-policy-local/1.1")
        self.assertEqual(audit_decision.decided_by, "dev4-risk-policy-agent")
        history = self.client.get("/api/agents/risk/history", **self.operator_headers)
        history_row = next(row for row in history.data["results"] if row.get("event_id") == "fixture-allow-policy" and row["kind"] == "EXECUTION")
        self.assertEqual(history_row["correlation_id"], data["correlation_id"])
        settlement = SettlementRecord.objects.get(settlement_id="TEST-ONLY-ALLOW-001")
        self.assertEqual(settlement.status, SettlementRecord.Status.SUBMITTED_BY_OWNER)
        self.assertTrue(AgentExecution.objects.filter(event__event_id="fixture-allow-settlement-request", agent__key="settlement").exists())
        self.assertTrue(all(row.correlation_id == data["correlation_id"] for row in SystemEvent.objects.filter(correlation_id=data["correlation_id"])))

        class PendingTestAdapter:
            source = "TEST_ONLY_HEDERA_OBSERVER"

            def observe(self, record):
                return {"status": "PENDING", "transaction_id": record.transaction_id, "network": "testnet", "observed_at": "2026-10-03T10:02:00Z"}

        with patch("command_center.management.commands.monitor_settlements.get_settlement_adapter", return_value=PendingTestAdapter()):
            call_command("monitor_settlements", "--once", verbosity=0)
        call_command("process_events", "--once", verbosity=0)
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, SettlementRecord.Status.OBSERVED_PENDING)

        settlement.last_checked_at = None
        settlement.save(update_fields=("last_checked_at",))

        class ConfirmedTestAdapter:
            source = "TEST_ONLY_HEDERA_OBSERVER"

            def observe(self, record):
                return {
                    "status": "CONFIRMED", "transaction_id": record.transaction_id, "network": "testnet",
                    "finality_confirmed": True, "consensus_timestamp": "2026-10-03T10:03:00.000Z",
                    "observed_at": "2026-10-03T10:03:01Z",
                }

        with patch("command_center.management.commands.monitor_settlements.get_settlement_adapter", return_value=ConfirmedTestAdapter()):
            call_command("monitor_settlements", "--once", verbosity=0)
        call_command("process_events", "--once", verbosity=0)
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, SettlementRecord.Status.CONFIRMED)
        self.assertEqual(settlement.transitions.count(), 5)
        self.assertFalse(AgentExecution.objects.filter(event__event_id__startswith="fixture-allow", output__signature_or_transfer_performed=True).exists())

    def test_phase1_to_5_synthetic_failed_ci_is_rejected_and_release_blocked(self):
        self._run_fixture_scenario("block_ci_failure")
        evidence = AgentExecution.objects.get(event__event_id="fixture-block-evidence")
        self.assertEqual(evidence.output["verdict"], "REJECTED")
        self.assertIn("CI_FAILED", evidence.output["hard_failures"])
        decision = AgentExecution.objects.get(event__event_id="fixture-block-policy")
        self.assertEqual(decision.output["decision"], "BLOCK")
        self.assertEqual(AgentAlert.objects.filter(alert_type="POLICY_BLOCKED").count(), 1)
        self.assertEqual(Agent.objects.get(key="risk").status, Agent.Status.IDLE)
        settlement = SettlementRecord.objects.get(settlement_id="TEST-ONLY-BLOCK-001")
        self.assertEqual(settlement.status, SettlementRecord.Status.POLICY_BLOCKED)

    def test_policy_missing_or_unrelated_evidence_fails_closed_to_human_review(self):
        self.assertEqual(self.ingest("phase5-review-settlement", "SETTLEMENT_REQUESTED", {"settlement_id": "TEST-ONLY-REVIEW-001"}, project_id="review-project").status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-review-policy", "POLICY_EVALUATION_REQUESTED", {
            "evaluation_id": "policy-review-001", "settlement_id": "TEST-ONLY-REVIEW-001",
            "milestone_id": "milestone-review", "planner_event_id": "planner-does-not-exist", "milestone_complete": True,
            "evidence_event_id": "evidence-does-not-exist", "client_approved": True,
            "conditions_met": True, "risk_level": "LOW", "source_refs": [],
        }, project_id="review-project", correlation_id="review-trace").status_code, 202)
        self.process_one()
        execution = AgentExecution.objects.get(event__event_id="phase5-review-policy")
        self.assertEqual(execution.output["decision"], "HUMAN_REVIEW")
        self.assertEqual(SettlementRecord.objects.get(settlement_id="TEST-ONLY-REVIEW-001").status, SettlementRecord.Status.POLICY_PENDING)

    @override_settings(
        FW_MODE_EVIDENCE="github",
        FW_GITHUB_TOKEN="test-read-only-token",
        FW_GITHUB_ALLOWED_REPOSITORIES={"emna/demo"},
    )
    def test_github_evidence_adapter_uses_api_facts_and_ignores_local_claims(self):
        self.assertEqual(self.ingest("phase5-github-proof", "EVIDENCE_REVIEW_REQUESTED", {
            "evidence_id": "github-proof-1", "work_id": "work-gh-1", "contributor_id": "emna-abdelli",
            "repository": "emna/demo", "contributor_login": "emna-abdelli",
            "commit_shas": ["c" * 40], "pull_request_numbers": [9],
            "commits": [{"sha": "d" * 40, "author_id": "spoofed"}],
            "pull_requests": [{"number": 999, "author_id": "spoofed", "state": "MERGED"}],
            "reviews": [], "ci_status": "SUCCESS",
        }).status_code, 202)
        responses = {
            "/repos/emna/demo/commits/" + "c" * 40: {"sha": "c" * 40, "author": {"login": "emna-abdelli"}, "committer": {"login": "emna-abdelli"}, "html_url": "https://github.com/emna/demo/commit/" + "c" * 40},
            "/repos/emna/demo/pulls/9": {"number": 9, "merged": True, "state": "closed", "user": {"login": "emna-abdelli"}, "head": {"sha": "e" * 40}, "html_url": "https://github.com/emna/demo/pull/9"},
            "/repos/emna/demo/pulls/9/commits?per_page=100": [{"sha": "c" * 40}],
            "/repos/emna/demo/pulls/9/reviews?per_page=100": [{"user": {"login": "reviewer"}, "state": "APPROVED", "submitted_at": "2026-10-02T12:00:00Z"}],
            "/repos/emna/demo/commits/" + "c" * 40 + "/check-runs?per_page=100": {"check_runs": []},
            "/repos/emna/demo/commits/" + "c" * 40 + "/status": {"state": "success"},
            "/repos/emna/demo/commits/" + "e" * 40 + "/check-runs?per_page=100": {"check_runs": [{"conclusion": "success"}]},
        }
        with patch("command_center.adapters.evidence.GitHubEvidenceAdapter._get", side_effect=lambda path: responses[path]):
            self.process_one()
        output = AgentExecution.objects.get(event__event_id="phase5-github-proof").output
        self.assertEqual(output["source"], "GITHUB_API")
        self.assertEqual(output["verdict"], "VERIFIED")
        self.assertFalse(output["synthetic_data"])
        self.assertIn("https://github.com/emna/demo/pull/9", output["source_refs"])

    @override_settings(FW_GITHUB_ALLOWED_REPOSITORIES={"emna/demo"})
    def test_github_evidence_adapter_collects_all_pages_of_commits_reviews_and_checks(self):
        commit_sha = "c" * 40
        base = "/repos/emna/demo"
        page_one_commits = [{"sha": f"{number:040x}"} for number in range(100)]
        page_one_reviews = [
            {"user": {"login": f"reviewer-{number}"}, "state": "COMMENTED"}
            for number in range(100)
        ]
        page_one_checks = [{"conclusion": "success"} for _ in range(100)]
        responses = {
            f"{base}/commits/{commit_sha}": {
                "sha": commit_sha,
                "author": {"login": "emna-abdelli"},
                "committer": {"login": "emna-abdelli"},
            },
            f"{base}/pulls/9": {
                "number": 9,
                "merged": True,
                "state": "closed",
                "user": {"login": "emna-abdelli"},
                "head": {"sha": commit_sha},
            },
            f"{base}/pulls/9/commits?per_page=100": page_one_commits,
            f"{base}/pulls/9/commits?per_page=100&page=2": [{"sha": commit_sha}],
            f"{base}/pulls/9/reviews?per_page=100": page_one_reviews,
            f"{base}/pulls/9/reviews?per_page=100&page=2": [
                {"user": {"login": "reviewer-final"}, "state": "APPROVED", "submitted_at": "2026-10-04T12:00:00Z"},
            ],
            f"{base}/commits/{commit_sha}/check-runs?per_page=100": {"check_runs": page_one_checks},
            f"{base}/commits/{commit_sha}/check-runs?per_page=100&page=2": {
                "check_runs": [{"conclusion": "success"}],
            },
        }
        adapter = GitHubEvidenceAdapter("")
        requested_paths = []

        def get_response(path):
            requested_paths.append(path)
            return responses[path]

        with patch.object(adapter, "_get", side_effect=get_response):
            evidence = adapter.fetch({
                "repository": "emna/demo",
                "commit_shas": [commit_sha],
                "pull_request_numbers": [9],
            })

        self.assertEqual(len(evidence["pull_requests"][0]["commit_shas"]), 101)
        self.assertEqual(len(evidence["reviews"]), 101)
        self.assertEqual(evidence["reviews"][-1]["state"], "APPROVED")
        self.assertEqual(evidence["ci_status"], "SUCCESS")
        self.assertIn(f"{base}/pulls/9/reviews?per_page=100&page=2", requested_paths)
        self.assertIn(f"{base}/commits/{commit_sha}/check-runs?per_page=100&page=2", requested_paths)

    @override_settings(
        FW_MODE_EVIDENCE="github",
        FW_GITHUB_TOKEN="test-read-only-token",
        FW_GITHUB_ALLOWED_REPOSITORIES={"emna/demo"},
    )
    def test_github_source_failure_is_retryable_and_never_becomes_verified(self):
        self.assertEqual(self.ingest("phase5-github-outage", "EVIDENCE_REVIEW_REQUESTED", {
            "evidence_id": "github-proof-outage", "work_id": "work-gh-outage", "contributor_id": "emna-abdelli",
            "repository": "emna/demo", "contributor_login": "emna-abdelli",
            "commit_shas": ["f" * 40], "pull_request_numbers": [10],
        }).status_code, 202)
        with patch("command_center.adapters.evidence.GitHubEvidenceAdapter._get", side_effect=EvidenceSourceError("GITHUB_RATE_LIMITED")):
            self.process_one()
        execution = AgentExecution.objects.get(event__event_id="phase5-github-outage")
        self.assertEqual(execution.status, AgentExecution.Status.RETRYABLE_FAILURE)
        self.assertEqual(execution.reason_code, "GITHUB_RATE_LIMITED")
        self.assertNotIn("verdict", execution.output)

    def test_agent_health_is_unknown_before_worker_heartbeat_and_available_after(self):
        before = self.client.get("/api/agents")
        self.assertTrue(all(row["health_status"] == "UNKNOWN" for row in before.data["results"]))
        self.assertEqual(self.ingest("phase5-heartbeat", "WORK_CREATED", {"work_id": "work-h", "title": "Heartbeat check"}).status_code, 202)
        self.process_one()
        after = self.client.get("/api/agents")
        self.assertTrue(all(row["health_status"] == "AVAILABLE" for row in after.data["results"]))

    def test_evidence_hash_alone_produces_unknown_verdict(self):
        response = self.ingest("phase5-proof-1", "EVIDENCE_SUBMITTED", {
            "evidence_id": "proof-11", "work_id": "work-9", "content_sha256": "a" * 64,
        })
        self.assertEqual(response.status_code, 202)
        self.process_one()
        execution = AgentExecution.objects.get(event__event_id="phase5-proof-1")
        self.assertEqual(execution.output["verdict"], "UNKNOWN")
        self.assertEqual(execution.reason_code, "OWNER_VERIFICATION_NOT_RECEIVED")

    def test_risk_agent_does_not_calculate_a_score_or_allow_high_risk(self):
        response = self.ingest("phase5-high-risk", "HIGH_RISK", {"risk_level": "HIGH"}, schema="1.0")
        self.assertEqual(response.status_code, 202)
        self.process_one()
        execution = AgentExecution.objects.get(event__event_id="phase5-high-risk")
        decision = AgentDecision.objects.get(event=execution.event)
        self.assertIsNone(execution.output["score"])
        self.assertEqual(decision.decision, AgentDecision.Decision.HUMAN_REVIEW)
        self.assertEqual(execution.reason_code, "AUTHORITATIVE_POLICY_NOT_RECEIVED")

    def test_settlement_requires_policy_then_tracks_owner_submission_and_finality(self):
        request = self.ingest("phase5-settle-request", "SETTLEMENT_REQUESTED", {"settlement_id": "stl-1"})
        self.assertEqual(request.status_code, 202)
        duplicate = self.ingest("phase5-settle-request", "SETTLEMENT_REQUESTED", {"settlement_id": "stl-1"})
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.data["duplicate"])
        self.process_one()
        record = SettlementRecord.objects.get(settlement_id="stl-1")
        self.assertEqual(record.status, SettlementRecord.Status.REQUESTED)

        self.assertEqual(self.ingest("phase5-policy-allow", "POLICY_DECIDED", {
            "decision_id": "policy-1", "settlement_id": "stl-1", "decision": "ALLOW",
            "reason_code": "POLICY_APPROVED", "policy_version": "local-policy/1",
        }).status_code, 202)
        self.process_one()
        record.refresh_from_db()
        self.assertEqual(record.status, SettlementRecord.Status.AUTHORIZED)

        self.assertEqual(self.ingest("phase5-settle-submitted", "SETTLEMENT_UPDATED", {
            "settlement_id": "stl-1", "status": "SUBMITTED", "transaction_id": "0.0.123@1.2", "network": "testnet",
        }).status_code, 202)
        self.process_one()
        record.refresh_from_db()
        self.assertEqual(record.status, SettlementRecord.Status.SUBMITTED_BY_OWNER)
        self.assertEqual(record.transaction_id, "0.0.123@1.2")

        self.assertEqual(self.ingest("phase5-settle-observed", "HEDERA_TRANSACTION_OBSERVED", {
            "settlement_id": "stl-1", "status": "PENDING", "transaction_id": "0.0.123@1.2", "network": "testnet",
        }).status_code, 202)
        self.process_one()
        record.refresh_from_db()
        self.assertEqual(record.status, SettlementRecord.Status.OBSERVED_PENDING)

        rejected = self.ingest("phase5-settle-no-finality", "HEDERA_TRANSACTION_OBSERVED", {
            "settlement_id": "stl-1", "status": "CONFIRMED", "transaction_id": "0.0.123@1.2",
        })
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.ingest("phase5-settle-confirmed", "HEDERA_TRANSACTION_OBSERVED", {
            "settlement_id": "stl-1", "status": "CONFIRMED", "transaction_id": "0.0.123@1.2",
            "finality_confirmed": True, "consensus_timestamp": "2026-10-03T10:01:00.000Z", "network": "testnet",
        }).status_code, 202)
        self.process_one()
        record.refresh_from_db()
        self.assertEqual(record.status, SettlementRecord.Status.CONFIRMED)
        self.assertEqual(record.consensus_timestamp, "2026-10-03T10:01:00.000Z")
        self.assertEqual(record.transitions.count(), 5)
        self.assertFalse(AgentExecution.objects.filter(event__event_id="phase5-settle-confirmed", output__signature_or_transfer_performed=True).exists())

        detail = self.client.get("/api/settlements/stl-1", **self.operator_headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["status"], SettlementRecord.Status.CONFIRMED)
        self.assertEqual(len(detail.data["transitions"]), 5)

    def test_illegal_confirmation_cannot_create_a_settlement_or_claim_success(self):
        response = self.ingest("phase5-illegal-confirm", "HEDERA_TRANSACTION_OBSERVED", {
            "settlement_id": "stl-missing", "status": "CONFIRMED", "transaction_id": "0.0.1@1.2",
            "finality_confirmed": True, "consensus_timestamp": "2026-10-03T10:01:00.000Z",
        })
        self.assertEqual(response.status_code, 202)
        self.process_one()
        self.assertFalse(SettlementRecord.objects.filter(settlement_id="stl-missing").exists())
        execution = AgentExecution.objects.get(event__event_id="phase5-illegal-confirm")
        self.assertEqual(execution.status, AgentExecution.Status.BLOCKED)
        self.assertEqual(execution.reason_code, "SETTLEMENT_REQUEST_NOT_FOUND")

    def test_owner_submission_before_policy_authorization_is_blocked(self):
        self.assertEqual(self.ingest("phase5-order", "SETTLEMENT_REQUESTED", {"settlement_id": "stl-order"}).status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-order-submit", "SETTLEMENT_UPDATED", {
            "settlement_id": "stl-order", "status": "SUBMITTED", "transaction_id": "0.0.77@1.2",
        }).status_code, 202)
        self.process_one()
        record = SettlementRecord.objects.get(settlement_id="stl-order")
        execution = AgentExecution.objects.get(event__event_id="phase5-order-submit")
        self.assertEqual(record.status, SettlementRecord.Status.REQUESTED)
        self.assertEqual(execution.status, AgentExecution.Status.BLOCKED)
        self.assertEqual(execution.reason_code, "ILLEGAL_SETTLEMENT_TRANSITION")
        self.assertEqual(record.transitions.count(), 1)

    def test_observed_settlement_failure_creates_one_trace_linked_alert(self):
        self.assertEqual(self.ingest("phase5-fail-request", "SETTLEMENT_REQUESTED", {"settlement_id": "stl-fail"}).status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-fail-policy", "POLICY_DECIDED", {
            "decision_id": "policy-fail", "settlement_id": "stl-fail", "decision": "ALLOW",
            "reason_code": "OK", "policy_version": "local-policy/1",
        }).status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-fail-submit", "SETTLEMENT_UPDATED", {
            "settlement_id": "stl-fail", "status": "SUBMITTED", "transaction_id": "0.0.99@1.2",
        }).status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-fail-observed", "TRANSACTION_FAILED", {
            "settlement_id": "stl-fail", "transaction_id": "0.0.99@1.2", "reason_code": "OWNER_REPORTED_FAILURE",
        }, schema="1.0").status_code, 202)
        self.process_one()
        record = SettlementRecord.objects.get(settlement_id="stl-fail")
        self.assertEqual(record.status, SettlementRecord.Status.FAILED)
        alert = AgentAlert.objects.get(alert_type="SETTLEMENT_FAILED")
        self.assertEqual(alert.trace_id, SystemEvent.objects.get(event_id="phase5-fail-observed").trace_id)

    def test_monitor_without_provider_records_unavailable_and_never_confirms(self):
        self.assertEqual(self.ingest("phase5-request-local", "SETTLEMENT_REQUESTED", {"settlement_id": "stl-monitor"}).status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-policy-local", "POLICY_DECIDED", {
            "decision_id": "policy-monitor", "settlement_id": "stl-monitor", "decision": "ALLOW",
            "reason_code": "OK", "policy_version": "local-policy/1",
        }).status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-submit-local", "SETTLEMENT_UPDATED", {
            "settlement_id": "stl-monitor", "status": "SUBMITTED", "transaction_id": "0.0.321@4.5",
        }).status_code, 202)
        self.process_one()

        call_command("monitor_settlements", "--once", verbosity=0)
        record = SettlementRecord.objects.get(settlement_id="stl-monitor")
        self.assertEqual(record.status, SettlementRecord.Status.SUBMITTED_BY_OWNER)
        self.assertEqual(record.monitor_attempts.get().outcome, SettlementMonitorAttempt.Outcome.UNAVAILABLE)
        self.assertNotEqual(record.status, SettlementRecord.Status.CONFIRMED)

    def test_expired_settlement_monitor_lease_is_reclaimed_and_released(self):
        from datetime import timedelta
        from django.utils import timezone

        WorkerLease.objects.create(
            name="settlement-monitor",
            owner="crashed-monitor",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        call_command("monitor_settlements", "--once", verbosity=0)
        lease = WorkerLease.objects.get(name="settlement-monitor")
        self.assertEqual(lease.owner, "")
        self.assertIsNone(lease.expires_at)

    def test_monitor_queues_idempotent_observation_for_the_event_worker(self):
        self.assertEqual(self.ingest("phase5-request-poller", "SETTLEMENT_REQUESTED", {"settlement_id": "stl-poller"}).status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-policy-poller", "POLICY_DECIDED", {
            "decision_id": "policy-poller", "settlement_id": "stl-poller", "decision": "ALLOW",
            "reason_code": "OK", "policy_version": "local-policy/1",
        }).status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-submit-poller", "SETTLEMENT_UPDATED", {
            "settlement_id": "stl-poller", "status": "SUBMITTED", "transaction_id": "0.0.456@7.8",
        }).status_code, 202)
        self.process_one()

        class TestAdapter:
            source = "test-observer"

            def observe(self, settlement):
                return {"status": "PENDING", "transaction_id": settlement.transaction_id, "network": "testnet", "observed_at": "2026-10-03T10:02:00Z"}

        with patch("command_center.management.commands.monitor_settlements.get_settlement_adapter", return_value=TestAdapter()):
            call_command("monitor_settlements", "--once", verbosity=0)
        queued = SystemEvent.objects.get(event_type="HEDERA_TRANSACTION_OBSERVED")
        self.assertEqual(EventOutbox.objects.get(event=queued).status, EventOutbox.Status.PENDING)
        call_command("process_events", "--once", verbosity=0)
        record = SettlementRecord.objects.get(settlement_id="stl-poller")
        self.assertEqual(record.status, SettlementRecord.Status.OBSERVED_PENDING)
        self.assertEqual(record.transitions.count(), 4)

    def test_monitor_rejects_confirmation_without_finality_evidence(self):
        self.assertEqual(self.ingest("phase5-request-invalid-source", "SETTLEMENT_REQUESTED", {"settlement_id": "stl-invalid-source"}).status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-policy-invalid-source", "POLICY_DECIDED", {
            "decision_id": "policy-invalid-source", "settlement_id": "stl-invalid-source", "decision": "ALLOW",
            "reason_code": "OK", "policy_version": "local-policy/1",
        }).status_code, 202)
        self.process_one()
        self.assertEqual(self.ingest("phase5-submit-invalid-source", "SETTLEMENT_UPDATED", {
            "settlement_id": "stl-invalid-source", "status": "SUBMITTED", "transaction_id": "0.0.789@1.1",
        }).status_code, 202)
        self.process_one()

        class InvalidAdapter:
            source = "invalid-test-source"

            def observe(self, settlement):
                return {"status": "CONFIRMED", "transaction_id": settlement.transaction_id}

        with patch("command_center.management.commands.monitor_settlements.get_settlement_adapter", return_value=InvalidAdapter()):
            call_command("monitor_settlements", "--once", verbosity=0)
        self.assertEqual(SettlementMonitorAttempt.objects.get().outcome, SettlementMonitorAttempt.Outcome.INVALID)
        self.assertFalse(SystemEvent.objects.filter(event_type="HEDERA_TRANSACTION_OBSERVED").exists())
        self.assertEqual(SettlementRecord.objects.get(settlement_id="stl-invalid-source").status, SettlementRecord.Status.SUBMITTED_BY_OWNER)

    def test_settlement_list_filters_and_paginates(self):
        for index in range(3):
            self.assertEqual(self.ingest(f"phase5-list-{index}", "SETTLEMENT_REQUESTED", {"settlement_id": f"stl-list-{index}"}).status_code, 202)
        call_command("process_events", "--once", verbosity=0)
        response = self.client.get("/api/settlements", {"project_id": "LOCAL-PROJECT-01", "limit": 2, "offset": 1}, **self.operator_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)
        bad_status = self.client.get("/api/settlements", {"status": "FAKE"}, **self.operator_headers)
        self.assertEqual(bad_status.status_code, 400)
