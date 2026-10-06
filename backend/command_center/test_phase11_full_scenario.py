import json
from datetime import date, timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import (
    AgentAction,
    AgentAlert,
    AgentDecision,
    AgentExecution,
    EvidenceSubmission,
    FreelancerProfile,
    ProjectMilestone,
    ProjectReference,
    SettlementRecord,
    SystemEvent,
)


User = get_user_model()
COMMIT_SHA = "a" * 40
HEDERA_TRANSACTION_ID = "0.0.900@1791112740.000000000"


class _JsonResponse:
    def __init__(self, data):
        self.body = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return self.body


@override_settings(
    DEBUG=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    FW_MODE_EVIDENCE="github",
    FW_GITHUB_TOKEN="test-only-server-token",
    FW_GITHUB_ALLOWED_REPOSITORIES={"scenario-org/approved", "scenario-org/ci-failure"},
    FW_MODE_HEDERA="live",
    FW_HEDERA_NETWORK="testnet",
    FW_HEDERA_MIRROR_NODE_URL="",
    FW_HEDERA_PROJECT_REFERENCES=(
        '{"SCENARIO-APPROVED":{"account_ids":["0.0.700"],"topic_ids":["0.0.701"],'
        '"token_ids":[],"contract_ids":[]}}'
    ),
    FW_HEDERA_TIMEOUT_SECONDS=2,
    FW_HEDERA_MAX_PAGES=3,
    FW_HEDERA_CACHE_SECONDS=0,
)
class Phase11FullScenarioTests(TestCase):
    password = "Scenario-Only-Strong-Password-2026!"

    def setUp(self):
        cache.clear()
        self.freelancer_client, self.freelancer = self._signup(
            "freelancer@example.test", "Scenario Freelancer", "scenario-dev"
        )
        self.client_user_client, self.client_user = self._signup(
            "client@example.test", "Scenario Client"
        )
        self.client_user.freelancer_profile.role = FreelancerProfile.Role.CLIENT
        self.client_user.freelancer_profile.save(update_fields=("role", "updated_at"))

    def _signup(self, email, display_name, github_login=""):
        client = APIClient()
        csrf = client.get("/api/auth/csrf")
        self.assertEqual(csrf.status_code, 200)
        response = client.post(
            "/api/auth/signup",
            {
                "display_name": display_name,
                "email": email,
                "password": self.password,
                "github_login": github_login,
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf.data["csrf_token"],
        )
        self.assertEqual(response.status_code, 201, response.data)
        return client, User.objects.get(email=email)

    def _create_project(self, external_id, repository):
        start = date.today() + timedelta(days=1)
        response = self.freelancer_client.post(
            "/api/freelancer/projects",
            {
                "external_id": external_id,
                "title": f"Validation {external_id}",
                "description": "Isolated Phase 11 end-to-end scenario",
                "total_hours": 100,
                "total_work_units": 100,
                "start_date": start.isoformat(),
                "target_deadline": (start + timedelta(days=30)).isoformat(),
                "github_repository": repository,
                "conditions": ["CI succeeds", "client approves"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["project_id"]

    def _github_response(self, request, requests):
        requests.append(request)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        path = urlsplit(request.full_url).path
        repository = "scenario-org/ci-failure" if "/ci-failure/" in path else "scenario-org/approved"
        base = f"/repos/{repository}"
        if path == f"{base}/commits/{COMMIT_SHA}":
            data = {
                "sha": COMMIT_SHA,
                "author": {"login": "scenario-dev"},
                "committer": {"login": "scenario-dev"},
                "html_url": f"https://github.com/{repository}/commit/{COMMIT_SHA}",
            }
        elif path in {f"{base}/pulls/17", f"{base}/pulls/18"}:
            number = 18 if path.endswith("/18") else 17
            data = {
                "number": number,
                "merged": True,
                "state": "closed",
                "user": {"login": "scenario-dev"},
                "head": {"sha": COMMIT_SHA},
                "html_url": f"https://github.com/{repository}/pull/{number}",
            }
        elif path in {f"{base}/pulls/17/commits", f"{base}/pulls/18/commits"}:
            data = [{"sha": COMMIT_SHA}]
        elif path in {f"{base}/pulls/17/reviews", f"{base}/pulls/18/reviews"}:
            number = 18 if "/18/" in path else 17
            data = [{
                "user": {"login": "independent-reviewer"},
                "state": "APPROVED",
                "submitted_at": "2026-10-04T10:00:00Z",
                "pull_request_number": number,
            }]
        elif path == f"{base}/commits/{COMMIT_SHA}/check-runs":
            conclusion = "failure" if repository.endswith("ci-failure") else "success"
            data = {"check_runs": [{"conclusion": conclusion}]}
        else:
            self.fail(f"Unexpected GitHub read endpoint: {path}")
        return _JsonResponse(data)

    def _hedera_response(self, request):
        path = urlsplit(request.full_url).path
        if path == "/api/v1/topics/0.0.701/messages":
            return _JsonResponse({
                "messages": [{"sequence_number": 8, "consensus_timestamp": "1791112740.000000000"}],
                "links": {"next": None},
            })
        if path == "/api/v1/transactions":
            return _JsonResponse({
                "transactions": [{
                    "transaction_id": HEDERA_TRANSACTION_ID,
                    "name": "CRYPTOTRANSFER",
                    "result": "SUCCESS",
                    "consensus_timestamp": "1791112740.000000000",
                }],
                "links": {"next": None},
            })
        self.fail(f"Unexpected Mirror Node read endpoint: {path}")

    def test_account_to_project_github_agents_policy_dashboard_and_hedera_with_refusal_paths(self):
        project_id = self._create_project("SCENARIO-APPROVED", "scenario-org/approved")
        rejected_project_id = self._create_project("SCENARIO-REJECTED", "scenario-org/ci-failure")
        forbidden_project_id = self._create_project("SCENARIO-FORBIDDEN", "attacker-org/private")

        add_client = self.freelancer_client.post(
            f"/api/freelancer/projects/{project_id}/members",
            {"email": self.client_user.email, "role": "CLIENT"},
            format="json",
        )
        self.assertEqual(add_client.status_code, 201, add_client.data)
        call_command("process_events", "--once", verbosity=0)
        milestones = list(ProjectMilestone.objects.filter(project__external_id=project_id))
        self.assertEqual(len(milestones), 5)
        milestone = milestones[0]

        accepted_evidence = self.freelancer_client.post(
            f"/api/freelancer/projects/{project_id}/evidence/github",
            {"evidence_id": "GH-SCENARIO-OK", "milestone_id": milestone.milestone_id,
             "commit_shas": [COMMIT_SHA], "pull_request_numbers": [17]},
            format="json",
        )
        rejected_evidence = self.freelancer_client.post(
            f"/api/freelancer/projects/{rejected_project_id}/evidence/github",
            {"evidence_id": "GH-SCENARIO-CI-FAIL", "commit_shas": [COMMIT_SHA],
             "pull_request_numbers": [18]},
            format="json",
        )
        self.assertEqual(accepted_evidence.status_code, 202, accepted_evidence.data)
        self.assertEqual(rejected_evidence.status_code, 202, rejected_evidence.data)
        self.assertNotIn("test-only-server-token", str(accepted_evidence.data))

        denied_evidence = self.freelancer_client.post(
            f"/api/freelancer/projects/{forbidden_project_id}/evidence/github",
            {"evidence_id": "GH-SCENARIO-FORBIDDEN", "commit_shas": [COMMIT_SHA],
             "pull_request_numbers": [19]},
            format="json",
        )
        self.assertEqual(denied_evidence.status_code, 403)
        self.assertEqual(denied_evidence.data["error"], "GITHUB_REPOSITORY_NOT_ALLOWLISTED")
        self.assertFalse(SystemEvent.objects.filter(
            project_id=forbidden_project_id, event_type="EVIDENCE_REVIEW_REQUESTED"
        ).exists())

        github_requests = []
        with patch(
            "command_center.adapters.evidence.urlopen",
            side_effect=lambda request, **_kwargs: self._github_response(request, github_requests),
        ):
            call_command("process_events", "--once", verbosity=0)
        self.assertGreaterEqual(len(github_requests), 10)
        self.assertTrue(all(request.get_method() == "GET" for request in github_requests))

        verified_identity_missing = AgentExecution.objects.get(event__event_id=accepted_evidence.data["event_id"])
        self.assertEqual(verified_identity_missing.agent.key, "evidence")
        self.assertEqual(verified_identity_missing.output["verdict"], "UNKNOWN")
        self.assertIn("GITHUB_IDENTITY_NOT_OAUTH_VERIFIED", verified_identity_missing.output["reasons"])
        self.assertEqual(
            EvidenceSubmission.objects.get(evidence_id="GH-SCENARIO-OK").status,
            EvidenceSubmission.Status.UNKNOWN,
        )

        failed_ci = AgentExecution.objects.get(event__event_id=rejected_evidence.data["event_id"])
        self.assertEqual(failed_ci.output["verdict"], "REJECTED")
        self.assertIn("CI_FAILED", failed_ci.output["hard_failures"])
        self.assertEqual(EvidenceSubmission.objects.get(evidence_id="GH-SCENARIO-CI-FAIL").status, "REJECTED")

        for item in milestones:
            completed_units = item.planned_work_units if item.pk == milestone.pk else 0
            progress = self.freelancer_client.post(
                f"/api/freelancer/projects/{project_id}/milestones/{item.milestone_id}/complete",
                {"completed_work_units": completed_units},
                format="json",
            )
            self.assertEqual(progress.status_code, 200, progress.data)
        self.client_user_client.post(
            f"/api/freelancer/projects/{project_id}/approvals",
            {"kind": "MILESTONE", "milestone_id": milestone.milestone_id,
             "decision": "REJECTED", "reason": "Client withheld approval for this run."},
            format="json",
        )
        approval = ProjectReference.objects.get(external_id=project_id).approvals.get()
        self.assertEqual(approval.decision, "REJECTED")
        denied_policy = self.freelancer_client.post(
            f"/api/freelancer/projects/{project_id}/policy-evaluations",
            {"milestone_id": milestone.milestone_id, "evidence_event_id": accepted_evidence.data["event_id"],
             "conditions_met": True, "risk_level": "LOW"},
            format="json",
        )
        self.assertEqual(denied_policy.status_code, 202, denied_policy.data)
        call_command("process_events", "--once", verbosity=0)
        blocked_decision = AgentDecision.objects.get(event__event_id=denied_policy.data["event_id"])
        self.assertEqual(blocked_decision.decision, "BLOCK")
        self.assertEqual(blocked_decision.reason_code, "CLIENT_APPROVAL_DENIED")

        dashboard_path = f"/api/projects/{project_id}/dashboard"
        activity_path = f"/api/projects/{project_id}/activity"
        detail_path = f"/api/freelancer/projects/{project_id}"
        with patch(
            "command_center.adapters.hedera.urlopen",
            side_effect=lambda request, **_kwargs: self._hedera_response(request),
        ):
            dashboard = self.freelancer_client.get(dashboard_path)
            transactions = self.freelancer_client.get(f"/api/projects/{project_id}/hedera/transactions")
        activity = self.freelancer_client.get(activity_path)
        detail = self.freelancer_client.get(detail_path)
        self.assertEqual(dashboard.status_code, 200, dashboard.data)
        self.assertEqual(dashboard.data["project"]["progress_percent"], 10)
        self.assertEqual(dashboard.data["source_status"]["hedera"], "available")
        self.assertEqual(dashboard.data["hedera_activity"][0]["kind"], "HCS_MESSAGE")
        self.assertIn("planner", {row["agent_id"] for row in dashboard.data["agent_activity"]})
        self.assertIn("evidence", {row["agent_id"] for row in dashboard.data["agent_activity"]})
        self.assertIn("risk", {row["agent_id"] for row in dashboard.data["agent_activity"]})
        self.assertTrue(any(row["event_id"] == denied_policy.data["event_id"] for row in activity.data["results"]))
        self.assertEqual(transactions.data["results"][0]["status"], "SUCCESS")
        self.assertEqual(transactions.data["results"][0]["transaction_id"], HEDERA_TRANSACTION_ID)
        self.assertTrue(transactions.data["results"][0]["hashscan_url"].startswith("https://hashscan.io/testnet/transaction/"))
        self.assertEqual(detail.data["decisions"][0]["decision"], "BLOCK")
        self.assertEqual(detail.data["evidence"][0]["repository"], "scenario-org/approved")
        self.assertTrue(AgentAlert.objects.filter(project_id=project_id, alert_type="POLICY_BLOCKED").exists())
        self.assertTrue(AgentAction.objects.filter(project_id=project_id).exists())
        self.assertFalse(SettlementRecord.objects.filter(
            project_id=project_id, status=SettlementRecord.Status.CONFIRMED
        ).exists())

        with patch("command_center.adapters.hedera.urlopen", side_effect=OSError("simulated unavailable")):
            unavailable_dashboard = self.freelancer_client.get(dashboard_path)
            unavailable_transactions = self.freelancer_client.get(
                f"/api/projects/{project_id}/hedera/transactions"
            )
        self.assertEqual(unavailable_dashboard.status_code, 200)
        self.assertEqual(unavailable_dashboard.data["source_status"]["hedera"], "UNAVAILABLE")
        self.assertEqual(unavailable_dashboard.data["hedera_activity"], [])
        self.assertEqual(unavailable_transactions.status_code, 503)
        self.assertEqual(unavailable_transactions.data["source_status"], "UNAVAILABLE")
        self.assertFalse(SettlementRecord.objects.filter(
            project_id=project_id, status=SettlementRecord.Status.CONFIRMED
        ).exists())
