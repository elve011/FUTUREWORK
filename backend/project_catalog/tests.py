import json
from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from .hedera_service import normalize_transaction_id
from .models import Milestone, Project, Tokenization, WorkAgreement, WorkUnit
from .planner import checkDeadlines, createMilestones


class HederaTransactionIdTests(SimpleTestCase):
    def test_sdk_transaction_id_is_normalized_for_mirror_node(self):
        self.assertEqual(
            normalize_transaction_id(
                "0.0.10856004@1791139693.187185525"
            ),
            "0.0.10856004-1791139693-187185525",
        )

    def test_canonical_transaction_id_is_unchanged(self):
        transaction_id = "0.0.10856004-1791139693-187185525"
        self.assertEqual(
            normalize_transaction_id(transaction_id), transaction_id
        )


class PlannerAcceptanceTests(SimpleTestCase):
    def make_agreement(self, total_units):
        project = SimpleNamespace(
            project_id="FW-001",
            total_units=total_units,
        )
        return SimpleNamespace(
            project=project,
            version=1,
            conditions="Livrer le travail convenu",
            value=Decimal("100.00"),
            deadline=date(2026, 10, 20),
        )

    def test_planner_preserves_total_for_standard_project(self):
        proposal = createMilestones(
            self.make_agreement(100), today=date(2026, 10, 5)
        )
        self.assertEqual(json.loads(json.dumps(proposal)), proposal)
        self.assertEqual(sum(item["units"] for item in proposal["milestones"]), 100)
        self.assertEqual(
            sum(
                unit["units"]
                for milestone in proposal["milestones"]
                for unit in milestone["workUnits"]
            ),
            100,
        )

    def test_planner_handles_one_unit(self):
        proposal = createMilestones(
            self.make_agreement(1), today=date(2026, 10, 5)
        )
        self.assertEqual(json.loads(json.dumps(proposal)), proposal)
        self.assertEqual(len(proposal["milestones"]), 1)
        self.assertEqual(proposal["milestones"][0]["units"], 1)

    def test_planner_handles_two_units_without_zero_unit_milestone(self):
        proposal = createMilestones(
            self.make_agreement(2), today=date(2026, 10, 5)
        )
        self.assertEqual(json.loads(json.dumps(proposal)), proposal)
        self.assertEqual(len(proposal["milestones"]), 2)
        self.assertEqual(
            [item["units"] for item in proposal["milestones"]], [1, 1]
        )


class PlannerDeadlineTests(TestCase):
    def test_deadline_check_reports_only_overdue_unfinished_milestones(self):
        project = Project.objects.create(
            title="Deadline test",
            client="0.0.1111",
            worker="0.0.2222",
            currency="HBAR",
            total_units=3,
        )
        overdue = Milestone.objects.create(
            project=project,
            title="Late work",
            units=1,
            deadline=date(2026, 10, 4),
        )
        Milestone.objects.create(
            project=project,
            title="Completed late work",
            units=1,
            deadline=date(2026, 10, 3),
            status=Milestone.Status.COMPLETED,
        )
        Milestone.objects.create(
            project=project,
            title="Future work",
            units=1,
            deadline=date(2026, 10, 7),
        )

        result = checkDeadlines(project, today=date(2026, 10, 6))

        self.assertEqual(
            result,
            [{
                "title": overdue.title,
                "deadline": "2026-10-04",
                "status": Milestone.Status.PLANNED,
            }],
        )


class ProjectWorkUnitAllocationTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.project = Project.objects.create(
            title="Demo",
            client="0.0.1111",
            worker="0.0.2222",
            currency="HBAR",
            total_units=10,
        )
        Tokenization.objects.create(
            project=self.project,
            name="Demo units",
            symbol="DEMO",
            total_supply=10,
            token_id="0.0.1234",
            status=Tokenization.Status.CREATED,
        )
        milestone = Milestone.objects.create(
            project=self.project,
            title="Delivery",
            units=10,
            deadline=date(2026, 10, 20),
        )
        WorkUnit.objects.create(milestone=milestone, title="Package 1", units=10)
        self.url = f"/api/projects/{self.project.project_id}/token/allocate"

    @patch("project_catalog.views.urlopen")
    def test_associated_worker_can_allocate_all_units_idempotently(self, mocked_urlopen):
        association_response = json.dumps(
            {"tokens": [{"token_id": "0.0.1234"}]}
        ).encode()
        mocked_urlopen.side_effect = [
            BytesIO(association_response),
            BytesIO(association_response),
        ]
        response = self.client_api.post(
            self.url, {"accountId": "0.0.2222"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["allocatedUnits"], 10)
        self.assertEqual(
            WorkUnit.objects.get().status, WorkUnit.Status.ALLOCATED
        )

        response = self.client_api.post(
            self.url, {"accountId": "0.0.2222"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["allocatedUnits"], 10)

    def test_different_account_cannot_allocate_project_units(self):
        response = self.client_api.post(
            self.url, {"accountId": "0.0.3333"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(WorkUnit.objects.get().status, WorkUnit.Status.PLANNED)

    @patch("project_catalog.views.urlopen")
    def test_unassociated_worker_cannot_allocate_units(self, mocked_urlopen):
        mocked_urlopen.return_value = BytesIO(json.dumps({"tokens": []}).encode())
        response = self.client_api.post(
            self.url, {"accountId": "0.0.2222"}, format="json"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "TOKEN_NOT_ASSOCIATED")


class WorkAgreementVersionTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.project = Project.objects.create(
            title="Agreement version test",
            client="0.0.1111",
            worker="0.0.2222",
            currency="HBAR",
            total_units=10,
        )
        self.url = f"/api/projects/{self.project.project_id}/agreement"

    def test_new_agreement_version_supersedes_previous_active_version(self):
        first = self.client_api.post(
            self.url,
            {"value": "10.00", "conditions": "Version one", "deadline": "2026-12-01"},
            format="json",
        )
        second = self.client_api.post(
            self.url,
            {"value": "20.00", "conditions": "Version two", "deadline": "2026-12-15"},
            format="json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["version"], 1)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data["version"], 2)
        history = self.client_api.get(
            f"/api/projects/{self.project.project_id}/agreements/history"
        )
        self.assertEqual(
            [(item["version"], item["status"]) for item in history.data],
            [(2, "ACTIVE"), (1, "SUPERSEDED")],
        )


class ProjectPlanHistoryTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.project = Project.objects.create(
            title="Version test",
            client="0.0.1111",
            worker="0.0.2222",
            currency="HBAR",
            total_units=10,
        )
        WorkAgreement.objects.create(
            project=self.project,
            version=1,
            value=Decimal("50.00"),
            conditions="Livraison test",
            deadline=date(2026, 12, 1),
        )
        self.base_url = f"/api/projects/{self.project.project_id}"

    def plan(self, title):
        return [{
            "title": title,
            "units": 10,
            "deadline": "2026-11-30",
            "workUnits": [{"title": f"{title} package", "units": 10}],
        }]

    def test_planner_api_returns_valid_editable_json_without_saving_it(self):
        response = self.client_api.post(f"{self.base_url}/planner/plan")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(json.dumps(response.data)), response.data)
        self.assertEqual(response.data["projectId"], self.project.project_id)
        self.assertEqual(
            sum(item["units"] for item in response.data["milestones"]), 10
        )
        self.assertEqual(self.project.milestones.count(), 0)

    def test_milestone_sum_mismatch_returns_explicit_validation_error(self):
        invalid_plan = self.plan("Incomplete")
        invalid_plan[0]["units"] = 9
        invalid_plan[0]["workUnits"][0]["units"] = 9

        response = self.client_api.post(
            f"{self.base_url}/milestones", invalid_plan, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "MILESTONE_UNITS_MISMATCH")
        self.assertEqual(response.data["expectedTotalUnits"], 10)
        self.assertEqual(response.data["receivedUnits"], 9)

    def test_plan_replacement_is_versioned_and_milestone_status_is_editable(self):
        first = self.client_api.post(
            f"{self.base_url}/milestones", self.plan("V1"), format="json"
        )
        self.assertEqual(first.status_code, 201)
        milestone_id = first.data[0]["milestoneId"].replace("M-", "")

        changed = self.client_api.patch(
            f"{self.base_url}/milestones/{milestone_id}/status",
            {"status": "COMPLETED"},
            format="json",
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.data["status"], "COMPLETED")

        updated = self.client_api.put(
            f"{self.base_url}/milestones", self.plan("V2"), format="json"
        )
        self.assertEqual(updated.status_code, 200)
        history = self.client_api.get(f"{self.base_url}/milestones/history")
        self.assertEqual([row["version"] for row in history.data], [2, 1])
        self.assertEqual(history.data[1]["milestones"][0]["title"], "V1")

        current_unit = WorkUnit.objects.get(milestone__project=self.project)
        current_unit.units = 6
        current_unit.status = WorkUnit.Status.ALLOCATED
        current_unit.save(update_fields=["units", "status"])
        WorkUnit.objects.create(
            milestone=current_unit.milestone,
            title="Released package",
            units=4,
            status=WorkUnit.Status.RELEASED,
        )

        replaced = self.client_api.put(
            f"{self.base_url}/milestones", self.plan("V3"), format="json"
        )
        self.assertEqual(replaced.status_code, 200)
        new_units = replaced.data[0]["workUnits"]
        self.assertEqual(
            sum(unit["units"] for unit in new_units if unit["status"] == "ALLOCATED"),
            6,
        )
        self.assertEqual(
            sum(unit["units"] for unit in new_units if unit["status"] == "RELEASED"),
            4,
        )
        history = self.client_api.get(f"{self.base_url}/milestones/history")
        self.assertEqual([row["version"] for row in history.data], [3, 2, 1])


class ProjectTokenBalanceTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.project = Project.objects.create(
            title="Balance test",
            client="0.0.1111",
            worker="0.0.2222",
            currency="HBAR",
            total_units=10,
        )
        Tokenization.objects.create(
            project=self.project,
            name="Balance units",
            symbol="BAL",
            total_supply=10,
            token_id="0.0.1234",
            transaction_id="0.0.1111-1700000000-1",
            status=Tokenization.Status.CREATED,
        )
        milestone = Milestone.objects.create(
            project=self.project,
            title="Delivery",
            units=10,
            deadline=date(2026, 12, 1),
        )
        WorkUnit.objects.create(
            milestone=milestone, title="Assigned", units=6,
            status=WorkUnit.Status.ALLOCATED,
        )
        WorkUnit.objects.create(
            milestone=milestone, title="Released", units=4,
            status=WorkUnit.Status.RELEASED,
        )

    @patch("project_catalog.views.urlopen")
    def test_token_counters_include_worker_mirror_node_balance(self, mocked_urlopen):
        mocked_urlopen.side_effect = [
            BytesIO(
                json.dumps({"tokens": [{"token_id": "0.0.1234", "balance": 4}]}).encode()
            ),
            BytesIO(
                json.dumps({"tokens": [{"token_id": "0.0.1234", "balance": 6}]}).encode()
            ),
        ]
        with patch.dict("os.environ", {"HEDERA_ACCOUNT_ID": "0.0.3333"}):
            response = self.client_api.get(
                f"/api/projects/{self.project.project_id}/token"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["treasuryAccountId"], "0.0.3333")
        self.assertEqual(
            response.data["unitBalances"],
            {
                "total": 10,
                "allocated": 6,
                "released": 4,
                "remaining": 0,
                "workerHtsBalance": 4,
                "treasuryHtsBalance": 6,
                "localReleasedUnits": 4,
                "releasedMatchesHtsBalance": True,
            },
        )


class ProjectTokenReleaseConfirmationTests(TestCase):
    def setUp(self):
        self.client_api = APIClient()
        self.project = Project.objects.create(
            title="Release test",
            client="0.0.1111",
            worker="0.0.2222",
            currency="HBAR",
            total_units=10,
        )
        Tokenization.objects.create(
            project=self.project,
            name="Release units",
            symbol="REL",
            total_supply=10,
            token_id="0.0.1234",
            status=Tokenization.Status.CREATED,
        )
        milestone = Milestone.objects.create(
            project=self.project,
            title="Delivery",
            units=10,
            deadline=date(2026, 12, 1),
        )
        self.work_unit = WorkUnit.objects.create(
            milestone=milestone,
            title="Package 1",
            units=10,
            status=WorkUnit.Status.ALLOCATED,
        )
        self.url = f"/api/projects/{self.project.project_id}/token/confirm-release"
        self.payload = {
            "accountId": "0.0.2222",
            "transactionId": "0.0.3333-1700000000-1",
        }

    @patch("project_catalog.views.urlopen")
    def test_successful_mirror_node_transfer_marks_units_released(self, mocked_urlopen):
        transaction_data = {
            "transactions": [{
                "result": "SUCCESS",
                "token_transfers": [
                    {"token_id": "0.0.1234", "account": "0.0.2222", "amount": 10},
                    {"token_id": "0.0.1234", "account": "0.0.3333", "amount": -10},
                ],
            }]
        }
        worker_balance = {"tokens": [{"token_id": "0.0.1234", "balance": 10}]}
        mocked_urlopen.side_effect = [
            BytesIO(json.dumps(transaction_data).encode()),
            BytesIO(json.dumps(worker_balance).encode()),
        ]

        with patch.dict("os.environ", {"HEDERA_ACCOUNT_ID": "0.0.3333"}):
            response = self.client_api.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["releasedUnits"], 10)
        self.assertEqual(response.data["workerHtsBalance"], 10)
        self.work_unit.refresh_from_db()
        self.assertEqual(self.work_unit.status, WorkUnit.Status.RELEASED)

    @patch("project_catalog.views.urlopen")
    def test_wrong_transfer_amount_does_not_mark_units_released(self, mocked_urlopen):
        transaction_data = {
            "transactions": [{
                "result": "SUCCESS",
                "token_transfers": [
                    {"token_id": "0.0.1234", "account": "0.0.2222", "amount": 9},
                    {"token_id": "0.0.1234", "account": "0.0.3333", "amount": -9},
                ],
            }]
        }
        mocked_urlopen.return_value = BytesIO(json.dumps(transaction_data).encode())

        with patch.dict("os.environ", {"HEDERA_ACCOUNT_ID": "0.0.3333"}):
            response = self.client_api.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "TRANSFER_NOT_CONFIRMED")
        self.work_unit.refresh_from_db()
        self.assertEqual(self.work_unit.status, WorkUnit.Status.ALLOCATED)

    def test_account_other_than_project_worker_is_rejected(self):
        response = self.client_api.post(
            self.url,
            {**self.payload, "accountId": "0.0.4444"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.work_unit.refresh_from_db()
        self.assertEqual(self.work_unit.status, WorkUnit.Status.ALLOCATED)
