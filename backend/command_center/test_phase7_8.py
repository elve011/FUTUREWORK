from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.test import override_settings
from rest_framework.test import APIClient

from .adapters.evidence import EvidenceSourceError, GitHubEvidenceAdapter
from .models import (
    AgentDecision, AgentExecution, EvidenceSubmission, EventOutbox, FreelancerProfile,
    ProjectAgreement, ProjectApproval, ProjectMember, ProjectMilestone,
    ProjectReference, SystemEvent,
)


User = get_user_model()


class GitHubAnonymousReadTests(SimpleTestCase):
    @patch("command_center.adapters.evidence.urlopen")
    def test_public_read_can_run_without_authorization_header(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        adapter = GitHubEvidenceAdapter(token="")

        self.assertEqual(adapter._get("/repos/public/repo"), {})

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.get_header("Authorization"))


class Phase7ProjectAndWorkflowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner@example.test", "owner@example.test", "safe-password-123")
        FreelancerProfile.objects.create(user=self.owner, display_name="Owner")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def create_project(self, **overrides):
        start = date.today() + timedelta(days=1)
        data = {
            "external_id": "PRJ-OWNER-001", "title": "Test project", "description": "Phase 7 flow",
            "total_hours": 100, "total_work_units": 100, "start_date": start.isoformat(),
            "target_deadline": (start + timedelta(days=30)).isoformat(),
            "conditions": ["CI must pass", "Client approves each milestone"],
        }
        data.update(overrides)
        return self.client.post("/api/freelancer/projects", data, format="json")

    def test_project_persists_agreement_and_queues_versioned_planner_event(self):
        response = self.create_project()
        self.assertEqual(response.status_code, 201, response.data)
        project = ProjectReference.objects.get(external_id="PRJ-OWNER-001")
        agreement = ProjectAgreement.objects.get(project=project)
        event = SystemEvent.objects.get(event_id=response.data["planner_event_id"])
        self.assertEqual(agreement.total_hours, 100)
        self.assertEqual(agreement.total_work_units, 100)
        self.assertEqual(agreement.approval_status, "PENDING")
        self.assertEqual(event.schema_version, "dev4-local/2.0")
        self.assertTrue(event.correlation_id)
        self.assertTrue(event.producer_id)
        self.assertEqual(EventOutbox.objects.get(event=event).status, "PENDING")
        self.assertEqual(ProjectMilestone.objects.filter(project=project).count(), 0)
        self.assertFalse(project.is_demo_only)

    def test_agreement_deadline_before_start_is_rejected(self):
        response = self.create_project(start_date="2027-05-10", target_deadline="2027-05-09")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ProjectReference.objects.filter(external_id="PRJ-OWNER-001").exists())

    def test_missing_agreement_numbers_remain_unknown_without_fake_plan(self):
        response = self.create_project(total_hours=None, total_work_units=None)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["planner_event_id"])
        self.assertEqual(response.data["plan_status"], "UNKNOWN_INSUFFICIENT_AGREEMENT_DATA")

    def test_update_and_member_project_access_are_scoped(self):
        self.assertEqual(self.create_project().status_code, 201)
        member = User.objects.create_user("member@example.test", "member@example.test", "safe-password-456")
        FreelancerProfile.objects.create(user=member, display_name="Member")
        response = self.client.post("/api/freelancer/projects/PRJ-OWNER-001/members", {"email": member.email, "role": "FREELANCER"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        other = User.objects.create_user("other@example.test", "other@example.test", "safe-password-789")
        FreelancerProfile.objects.create(user=other, display_name="Other")
        outsider = APIClient(); outsider.force_authenticate(other)
        self.assertEqual(outsider.get("/api/freelancer/projects/PRJ-OWNER-001").status_code, 404)
        self.assertEqual(outsider.patch("/api/freelancer/projects/PRJ-OWNER-001", {"title": "Takeover"}, format="json").status_code, 404)
        client = APIClient(); client.force_authenticate(member)
        self.assertEqual(client.get("/api/freelancer/projects").data["count"], 1)
        self.assertEqual(client.get("/api/freelancer/projects/PRJ-OWNER-001").status_code, 200)
        self.assertEqual(client.patch("/api/freelancer/projects/PRJ-OWNER-001", {"title": "Member edit"}, format="json").status_code, 403)
        update = self.client.patch("/api/freelancer/projects/PRJ-OWNER-001", {"title": "Updated title"}, format="json")
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.data["title"], "Updated title")

    def test_local_planner_evidence_and_risk_workflow_is_persisted_and_correlated(self):
        response = self.create_project()
        project_id = response.data["project_id"]
        call_command("process_events", "--once", verbosity=0)
        project = ProjectReference.objects.get(external_id=project_id)
        milestones = list(project.milestones.all())
        self.assertEqual(len(milestones), 5)
        self.assertEqual(sum(item.planned_work_units for item in milestones), 100)
        self.assertTrue(all(item.status == "PROPOSED" and item.completed_work_units is None for item in milestones))
        self.assertEqual(project.agreement.plan_status, "PROPOSED_REQUIRES_HUMAN_APPROVAL")

        milestone = milestones[0]
        evidence_response = self.client.post(f"/api/freelancer/projects/{project_id}/evidence/test", {
            "evidence_id": "EV-TEST-001", "milestone_id": milestone.milestone_id,
            "commits": [{"sha": "abcdef0123456789", "author_id": "owner@example.test"}],
            "pull_requests": [{"number": 1, "author_id": "owner@example.test", "state": "MERGED", "commit_shas": ["abcdef0123456789"]}],
            "reviews": [{"pull_request_number": 1, "reviewer_id": "reviewer@example.test", "state": "APPROVED"}],
            "ci_status": "SUCCESS",
        }, format="json")
        self.assertEqual(evidence_response.status_code, 202, evidence_response.data)
        call_command("process_events", "--once", verbosity=0)
        evidence = EvidenceSubmission.objects.get(project=project, evidence_id="EV-TEST-001")
        self.assertEqual(evidence.status, "VERIFIED")
        self.assertEqual(evidence.source, "TEST_ONLY")
        self.assertTrue(evidence.is_demo_only)
        self.assertEqual(evidence.score, 100)

        milestone_response = self.client.post(f"/api/freelancer/projects/{project_id}/milestones/{milestone.milestone_id}/complete", {
            "completed_work_units": milestone.planned_work_units,
        }, format="json")
        self.assertEqual(milestone_response.status_code, 200)
        self.assertEqual(milestone_response.data["status"], "COMPLETED")
        self.assertEqual(ProjectMilestone.objects.get(pk=milestone.pk).status, "COMPLETED")
        policy_response = self.client.post(f"/api/freelancer/projects/{project_id}/policy-evaluations", {
            "milestone_id": milestone.milestone_id, "evidence_event_id": evidence.source_event_id,
            "conditions_met": True, "risk_level": "LOW",
        }, format="json")
        self.assertEqual(policy_response.status_code, 202, policy_response.data)
        call_command("process_events", "--once", verbosity=0)
        decision = AgentDecision.objects.get(event__event_id=policy_response.data["event_id"])
        self.assertEqual(decision.decision, "HUMAN_REVIEW")
        self.assertEqual(decision.reason_code, "REQUIRED_POLICY_FACT_UNKNOWN")
        self.assertEqual(decision.policy_version, "dev4-policy-local/1.1")

        client_user = User.objects.create_user("client@example.test", "client@example.test", "safe-password-client")
        FreelancerProfile.objects.create(user=client_user, display_name="Client", role=FreelancerProfile.Role.CLIENT)
        self.client.post(f"/api/freelancer/projects/{project_id}/members", {"email": client_user.email, "role": "CLIENT"}, format="json")
        client = APIClient(); client.force_authenticate(client_user)
        self.assertEqual(client.post(f"/api/freelancer/projects/{project_id}/evidence/test", {}, format="json").status_code, 403)
        approval = client.post(f"/api/freelancer/projects/{project_id}/approvals", {
            "kind": "MILESTONE", "milestone_id": milestone.milestone_id, "decision": "APPROVED", "reason": "Reviewed delivery",
        }, format="json")
        self.assertEqual(approval.status_code, 201, approval.data)
        successful_policy = self.client.post(f"/api/freelancer/projects/{project_id}/policy-evaluations", {
            "milestone_id": milestone.milestone_id, "evidence_event_id": evidence.source_event_id,
            "conditions_met": True, "risk_level": "LOW",
        }, format="json")
        self.assertEqual(successful_policy.status_code, 202, successful_policy.data)
        self.assertTrue(SystemEvent.objects.get(event_id=successful_policy.data["event_id"]).payload["milestone_complete"])
        call_command("process_events", "--once", verbosity=0)
        successful_decision = AgentDecision.objects.get(event__event_id=successful_policy.data["event_id"])
        self.assertEqual(successful_decision.decision, "ALLOW", successful_decision.reason_code)
        self.assertEqual(successful_decision.reason_code, "ALL_LOCAL_POLICY_GATES_PASSED")
        self.assertEqual(AgentExecution.objects.filter(event__project_id=project_id).count(), 4)

        detail = self.client.get(f"/api/freelancer/projects/{project_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.data["milestones"]), 5)
        self.assertEqual(detail.data["evidence"][0]["source"], "TEST_ONLY")
        self.assertEqual(detail.data["decisions"][0]["decision"], "ALLOW")

    def test_failed_ci_is_rejected_and_not_counted_as_verified(self):
        self.create_project()
        call_command("process_events", "--once", verbosity=0)
        response = self.client.post("/api/freelancer/projects/PRJ-OWNER-001/evidence/test", {
            "evidence_id": "EV-CI-FAIL", "commits": [{"sha": "abcdef0123456789", "author_id": "owner@example.test"}],
            "pull_requests": [{"number": 2, "author_id": "owner@example.test", "state": "MERGED", "commit_shas": ["abcdef0123456789"]}],
            "reviews": [{"pull_request_number": 2, "reviewer_id": "reviewer@example.test", "state": "APPROVED"}],
            "ci_status": "FAILURE",
        }, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        call_command("process_events", "--once", verbosity=0)
        evidence = EvidenceSubmission.objects.get(evidence_id="EV-CI-FAIL")
        self.assertEqual(evidence.status, "REJECTED")
        self.assertEqual(evidence.score, 75)
        self.assertIn("CI_FAILED", evidence.reasons)

    @override_settings(FW_GITHUB_ALLOWED_REPOSITORIES={"approved-org/approved-repo"}, FW_GITHUB_TOKEN="server-only-token")
    def test_github_evidence_is_allowlisted_server_side_and_token_is_not_returned(self):
        self.owner.freelancer_profile.github_login = "owner-gh"
        self.owner.freelancer_profile.save(update_fields=["github_login", "updated_at"])
        response = self.create_project(github_repository="approved-org/approved-repo")
        self.assertEqual(response.status_code, 201, response.data)
        evidence = self.client.post(f"/api/freelancer/projects/{response.data['project_id']}/evidence/github", {
            "evidence_id": "GH-REF-001", "commit_shas": ["abcdef0123456789"], "pull_request_numbers": [42],
        }, format="json")
        self.assertEqual(evidence.status_code, 202, evidence.data)
        self.assertEqual(evidence.data["source"], "GITHUB_API")
        self.assertNotIn("server-only-token", str(evidence.data))
        event = SystemEvent.objects.get(event_id=evidence.data["event_id"])
        self.assertEqual(event.payload["repository"], "approved-org/approved-repo")
        self.assertEqual(event.payload["contributor_login"], "owner-gh")
        self.assertEqual(EvidenceSubmission.objects.get(evidence_id="GH-REF-001").source, "GITHUB_API")
        with patch("command_center.adapters.evidence.GitHubEvidenceAdapter.fetch", return_value={
            "source": "GITHUB_API", "repository": "approved-org/approved-repo",
            "commits": [{"sha": "abcdef0123456789", "author_id": "owner-gh", "committer_id": "owner-gh"}],
            "pull_requests": [{"number": 42, "author_id": "owner-gh", "state": "MERGED", "commit_shas": ["abcdef0123456789"]}],
            "reviews": [{"pull_request_number": 42, "reviewer_id": "reviewer", "state": "APPROVED"}],
            "ci_status": "SUCCESS", "source_refs": ["https://github.com/approved-org/approved-repo/pull/42"],
        }):
            call_command("process_events", "--once", verbosity=0)
        persisted = EvidenceSubmission.objects.get(evidence_id="GH-REF-001")
        execution = AgentExecution.objects.filter(event__event_id=evidence.data["event_id"]).first()
        self.assertEqual(persisted.status, "UNKNOWN", {"event": event.event_id, "outbox": event.outbox.status, "execution": execution.output if execution else None})
        self.assertIn("GITHUB_IDENTITY_NOT_OAUTH_VERIFIED", persisted.reasons)

    @override_settings(FW_GITHUB_ALLOWED_REPOSITORIES=set(), FW_GITHUB_TOKEN="server-only-token")
    def test_github_evidence_rejects_repository_not_on_allowlist(self):
        self.owner.freelancer_profile.github_login = "owner-gh"
        self.owner.freelancer_profile.save(update_fields=["github_login", "updated_at"])
        response = self.create_project(github_repository="unapproved-org/private-repo")
        evidence = self.client.post(f"/api/freelancer/projects/{response.data['project_id']}/evidence/github", {
            "evidence_id": "GH-NOT-ALLOWED", "commit_shas": ["abcdef0123456789"], "pull_request_numbers": [42],
        }, format="json")
        self.assertEqual(evidence.status_code, 403)
        self.assertEqual(evidence.data["error"], "GITHUB_REPOSITORY_NOT_ALLOWLISTED")
        self.assertFalse(SystemEvent.objects.filter(event_type="EVIDENCE_REVIEW_REQUESTED").exists())

    @override_settings(FW_GITHUB_ALLOWED_REPOSITORIES={"approved-org/approved-repo"}, FW_GITHUB_TOKEN="")
    def test_github_source_failure_marks_submission_unknown_with_reason(self):
        self.owner.freelancer_profile.github_login = "owner-gh"
        self.owner.freelancer_profile.save(update_fields=["github_login", "updated_at"])
        project_response = self.create_project(github_repository="approved-org/approved-repo")
        project_id = project_response.data["project_id"]
        evidence_response = self.client.post(
            f"/api/freelancer/projects/{project_id}/evidence/github",
            {"evidence_id": "GH-SOURCE-UNAVAILABLE", "commit_shas": ["abcdef0123456789"],
             "pull_request_numbers": [42]},
            format="json",
        )
        self.assertEqual(evidence_response.status_code, 202, evidence_response.data)

        with patch(
            "command_center.adapters.evidence.GitHubEvidenceAdapter.fetch",
            side_effect=EvidenceSourceError("GITHUB_HTTP_409"),
        ):
            call_command("process_events", "--once", verbosity=0)

        evidence = EvidenceSubmission.objects.get(evidence_id="GH-SOURCE-UNAVAILABLE")
        self.assertEqual(evidence.status, EvidenceSubmission.Status.UNKNOWN)
        self.assertEqual(evidence.reasons, ["GITHUB_HTTP_409"])

    def test_duplicate_evidence_identifier_is_rejected_without_duplicate_event(self):
        self.create_project()
        data = {"evidence_id": "EV-DUP", "commits": [], "pull_requests": [], "reviews": [], "ci_status": "PENDING"}
        first = self.client.post("/api/freelancer/projects/PRJ-OWNER-001/evidence/test", data, format="json")
        second = self.client.post("/api/freelancer/projects/PRJ-OWNER-001/evidence/test", data, format="json")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(SystemEvent.objects.filter(event_type="EVIDENCE_REVIEW_REQUESTED").count(), 1)


class Phase8ContractTests(TestCase):
    def test_v2_requires_producer_and_correlation_and_rejects_unknown_version(self):
        from .serializers import EVENT_TYPES, LOCAL_PAYLOAD_SERIALIZERS, IngestEventSerializer
        self.assertEqual(set(LOCAL_PAYLOAD_SERIALIZERS), set(EVENT_TYPES))
        base = {
            "schema_version": "dev4-local/2.0", "event_id": "v2-e1", "event_type": "WORK_CREATED",
            "project_id": "P-1", "occurred_at": "2026-10-04T10:00:00Z", "source": "MANUAL",
            "payload": {"work_id": "W-1", "title": "Work"},
        }
        self.assertFalse(IngestEventSerializer(data=base).is_valid())
        complete = {**base, "producer_id": "test-producer", "correlation_id": "P-1"}
        self.assertTrue(IngestEventSerializer(data=complete).is_valid())
        unknown = {**complete, "schema_version": "dev4-local/99.0"}
        self.assertFalse(IngestEventSerializer(data=unknown).is_valid())
