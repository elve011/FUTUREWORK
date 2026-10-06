import json
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from .adapters.hedera import HederaObserverUnavailable, MirrorNodeObserver
from .hedera_payment import HederaPaymentSubmissionError
from .models import (
    EvidenceSubmission,
    FreelancerProfile,
    ProjectApproval,
    ProjectAuditLog,
    ProjectMilestone,
    ProjectReference,
    SettlementRecord,
)


class _Response:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return self.data


@override_settings(
    FW_HEDERA_NETWORK="testnet",
    FW_HEDERA_PROJECT_REFERENCES='{"project-a":{"account_ids":["0.0.123"],"topic_ids":["0.0.456"]}}',
    FW_HEDERA_TIMEOUT_SECONDS=2,
    FW_HEDERA_MAX_PAGES=2,
    FW_HEDERA_CACHE_SECONDS=0,
)
class MirrorNodeObserverTests(TestCase):
    def setUp(self):
        cache.clear()
        self.observer = MirrorNodeObserver()

    @patch("command_center.adapters.hedera.urlopen")
    def test_account_transactions_are_normalized_without_inventing_confirmation(self, urlopen):
        urlopen.return_value = _Response({
            "transactions": [
                {"transaction_id": "0.0.123@1710000000.000000000", "name": "CRYPTOTRANSFER", "result": "SUCCESS", "consensus_timestamp": "1710000000.000000000"},
                {"transaction_id": "0.0.123@1710000001.000000000", "name": "CRYPTOTRANSFER", "result": "FAIL_INVALID", "consensus_timestamp": None},
                {"transaction_id": "0.0.123@1710000002.000000000", "name": "CRYPTOTRANSFER", "result": "PENDING", "consensus_timestamp": None},
            ],
            "links": {"next": None},
        })
        rows = self.observer.get_transactions("project-a")
        confirmed, unconfirmed, pending = rows[0], rows[1], rows[2]
        self.assertEqual(confirmed["status"], "SUCCESS")
        self.assertEqual(confirmed["consensus_timestamp"], "2024-03-09T16:00:00.000000000Z")
        self.assertEqual(confirmed["hashscan_url"], "https://hashscan.io/testnet/transaction/0.0.123-1710000000.000000000")
        self.assertEqual(unconfirmed["status"], "FAIL_INVALID")
        self.assertIsNone(unconfirmed["consensus_timestamp"])
        self.assertEqual(pending["status"], "PENDING")
        self.assertIsNone(pending["consensus_timestamp"])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 2)

    @patch("command_center.adapters.hedera.urlopen")
    def test_topic_message_pagination_stays_on_configured_mirror_host(self, urlopen):
        urlopen.side_effect = [
            _Response({"messages": [{"sequence_number": 4, "consensus_timestamp": "1710000000.100000000"}],
                       "links": {"next": "/api/v1/topics/0.0.456/messages?limit=100&sequencenumber=lt%3A4"}}),
            _Response({"messages": [{"sequence_number": 3, "consensus_timestamp": None}], "links": {"next": None}}),
        ]
        rows = self.observer.get_activity("project-a")
        topic_rows = [row for row in rows if row["kind"] == "HCS_MESSAGE"]
        self.assertEqual([row["id"] for row in topic_rows], ["0.0.456:4", "0.0.456:3"])
        self.assertEqual(topic_rows[0]["consensus_timestamp"], "2024-03-09T16:00:00.100000000Z")
        self.assertIsNone(topic_rows[1]["consensus_timestamp"])
        self.assertEqual(urlopen.call_count, 2)

    @patch("command_center.adapters.hedera.urlopen")
    def test_temporary_network_error_is_retried_once(self, urlopen):
        urlopen.side_effect = [OSError("network unavailable"), _Response({"transactions": [], "links": {"next": None}})]
        self.assertEqual(self.observer.get_transactions("project-a"), [])
        self.assertEqual(urlopen.call_count, 2)

    @patch("command_center.adapters.hedera.urlopen")
    def test_page_limit_does_not_return_a_truncated_feed_as_complete(self, urlopen):
        urlopen.return_value = _Response({
            "transactions": [{"transaction_id": "observed"}],
            "links": {"next": "/api/v1/transactions?limit=100&timestamp=lt%3A1710000000.000000000"},
        })
        with self.assertRaisesRegex(HederaObserverUnavailable, "HEDERA_PAGINATION_LIMIT_REACHED"):
            self.observer.get_transactions("project-a")

    @override_settings(FW_HEDERA_MIRROR_NODE_URL="https://mainnet-public.mirrornode.hedera.com/api/v1")
    def test_endpoint_from_other_network_is_rejected(self):
        with self.assertRaisesRegex(HederaObserverUnavailable, "HEDERA_MIRROR_NODE_URL_INVALID"):
            MirrorNodeObserver()

    @override_settings(FW_HEDERA_CACHE_SECONDS=10)
    @patch("command_center.adapters.hedera.urlopen")
    def test_successful_page_is_cached_briefly(self, urlopen):
        urlopen.return_value = _Response({"transactions": [], "links": {"next": None}})
        observer = MirrorNodeObserver()
        self.assertEqual(observer.get_transactions("project-a"), [])
        self.assertEqual(observer.get_transactions("project-a"), [])
        self.assertEqual(urlopen.call_count, 1)

    @patch("command_center.adapters.hedera.urlopen", side_effect=OSError("offline"))
    def test_source_failure_is_explicit(self, _urlopen):
        with self.assertRaisesRegex(HederaObserverUnavailable, "HEDERA_SOURCE_UNAVAILABLE"):
            self.observer.get_transactions("project-a")

    @override_settings(FW_HEDERA_NETWORK="previewnet")
    def test_unsupported_network_is_rejected(self):
        with self.assertRaisesRegex(HederaObserverUnavailable, "HEDERA_NETWORK_UNSUPPORTED"):
            MirrorNodeObserver()

    def test_unknown_project_has_no_observations_and_invalid_ids_are_rejected(self):
        self.assertFalse(self.observer.is_configured("project-b"))
        with override_settings(FW_HEDERA_PROJECT_REFERENCES='{"project-a":{"account_ids":["0.0.123;bad"]}}'):
            with self.assertRaisesRegex(HederaObserverUnavailable, "HEDERA_PROJECT_REFERENCES_INVALID"):
                MirrorNodeObserver().get_transactions("project-a")

    @override_settings(
        FW_MODE_HEDERA="live",
        FW_OPERATOR_API_KEYS={"test-operator": "test-secret"},
        FW_HEDERA_PROJECT_REFERENCES='{"FW-DEMO-001":{"account_ids":["0.0.123"]}}',
    )
    @patch("command_center.adapters.hedera.urlopen", side_effect=OSError("offline"))
    def test_dashboard_exposes_unavailable_state_when_mirror_node_is_down(self, _urlopen):
        client = APIClient()
        response = client.get(
            "/api/projects/FW-DEMO-001/dashboard",
            HTTP_X_OPERATOR_ID="test-operator",
            HTTP_X_OPERATOR_KEY="test-secret",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["source_status"]["hedera"], "UNAVAILABLE")

    @override_settings(FW_HEDERA_NETWORK="mainnet")
    @patch("command_center.adapters.hedera.urlopen")
    def test_mainnet_hashscan_link_matches_selected_network(self, urlopen):
        urlopen.return_value = _Response({
            "transactions": [{"transaction_id": "0.0.123@1710000000.000000000", "name": "CRYPTOTRANSFER",
                              "result": "SUCCESS", "consensus_timestamp": "1710000000.000000000"}],
            "links": {"next": None},
        })
        row = MirrorNodeObserver().get_transactions("project-a")[0]
        self.assertTrue(row["hashscan_url"].startswith("https://hashscan.io/mainnet/transaction/"))


@override_settings(DEBUG=True)
class HederaDemoSeedTests(TestCase):
    def test_seed_creates_idempotent_completed_demo_project_for_local_wallet_testing(self):
        call_command("seed_hedera_demo", stdout=StringIO())
        call_command("seed_hedera_demo", stdout=StringIO())

        user = get_user_model().objects.get(email="hedera.demo@example.test")
        project = ProjectReference.objects.get(external_id="HEDERA-DEMO-001")
        milestones = ProjectMilestone.objects.filter(project=project)
        evidence = EvidenceSubmission.objects.filter(project=project, status="VERIFIED")

        self.assertTrue(user.freelancer_profile.is_demo_only)
        self.assertEqual(user.freelancer_profile.github_login, "elve011")
        self.assertEqual(project.owner_id, user.pk)
        self.assertTrue(project.is_demo_only)
        self.assertEqual(milestones.count(), 3)
        self.assertEqual(sum(row.completed_work_units for row in milestones), 100)
        self.assertTrue(all(row.status == ProjectMilestone.Status.COMPLETED for row in milestones))
        self.assertEqual(project.agreement.github_repository, "elve011/repo-test")
        self.assertEqual(evidence.count(), 3)
        self.assertEqual(ProjectApproval.objects.filter(project=project, decision="APPROVED").count(), 4)

        client = APIClient()
        client.force_authenticate(user=user)
        registry = client.get("/api/freelancer/projects")
        detail = client.get("/api/freelancer/projects/HEDERA-DEMO-001")
        self.assertEqual(registry.status_code, 200)
        self.assertEqual([row["project_id"] for row in registry.data["results"]], ["HEDERA-DEMO-001"])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.data["milestones"]), 3)
        self.assertEqual(len(detail.data["evidence"]), 3)
        milestone_approvals = [row for row in detail.data["approvals"] if row["kind"] == "MILESTONE"]
        self.assertEqual({row["milestone_id"] for row in milestone_approvals}, {row.milestone_id for row in milestones})


@override_settings(
    DEBUG=True,
    FW_HEDERA_NETWORK="testnet",
    FW_HEDERA_DEMO_OPERATOR_ACCOUNT_ID="0.0.10685730",
    FW_HEDERA_DEMO_OPERATOR_PRIVATE_KEY="ab" * 32,
    FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID="0.0.10868485",
)
class HederaDemoTransferApiTests(TestCase):
    def setUp(self):
        call_command("seed_hedera_demo", stdout=StringIO())
        self.user = get_user_model().objects.get(email="hedera.demo@example.test")
        self.milestone = ProjectMilestone.objects.get(milestone_id="HEDERA-DEMO-001-MS-01")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.config_path = "/api/freelancer/projects/HEDERA-DEMO-001/hedera/testnet/config"
        self.transfer_path = "/api/freelancer/projects/HEDERA-DEMO-001/hedera/testnet/transfers"

    def test_config_never_returns_signing_key_and_exposes_testnet_accounts(self):
        response = self.client.get(self.config_path)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["enabled"])
        self.assertEqual(response.data["network"], "testnet")
        self.assertEqual(response.data["operator_account_id"], "0.0.10685730")
        self.assertEqual(response.data["recipient_account_id"], "0.0.10868485")
        self.assertNotIn("private_key", response.data)
        self.assertNotIn("ab" * 32, str(response.data))

    @patch("command_center.views.submit_testnet_hbar_transfer", return_value="0.0.10685730@1770000000.000000000")
    def test_transfer_records_successful_testnet_transaction_and_prevents_duplicate(self, send_transfer):
        payload = {"milestone_id": self.milestone.milestone_id, "amount_hbar": "0.1", "confirm": True}
        response = self.client.post(self.transfer_path, payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "SUBMITTED_BY_OWNER")
        self.assertEqual(response.data["network"], "testnet")
        self.assertEqual(response.data["transaction_id"], "0.0.10685730@1770000000.000000000")
        self.assertTrue(response.data["hashscan_url"].startswith("https://hashscan.io/testnet/transaction/"))
        record = SettlementRecord.objects.get(settlement_id=response.data["settlement_id"])
        self.assertEqual(record.transaction_id, response.data["transaction_id"])
        self.assertEqual(record.status, SettlementRecord.Status.SUBMITTED_BY_OWNER)
        self.assertTrue(ProjectAuditLog.objects.filter(project__external_id="HEDERA-DEMO-001", action="HEDERA_TESTNET_TRANSFER_SUBMITTED").exists())

        duplicate = self.client.post(self.transfer_path, payload, format="json")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.data["error"], "HEDERA_MILESTONE_ALREADY_PAID")
        send_transfer.assert_called_once()

    @patch("command_center.views.submit_testnet_hbar_transfer")
    def test_only_confirmed_fixed_amount_and_eligible_demo_milestones_can_send(self, send_transfer):
        missing_confirmation = self.client.post(
            self.transfer_path,
            {"milestone_id": self.milestone.milestone_id, "amount_hbar": "0.1"},
            format="json",
        )
        too_much = self.client.post(
            self.transfer_path,
            {"milestone_id": self.milestone.milestone_id, "amount_hbar": "1", "confirm": True},
            format="json",
        )
        unknown_milestone = self.client.post(
            self.transfer_path,
            {"milestone_id": "not-a-demo-milestone", "amount_hbar": "0.1", "confirm": True},
            format="json",
        )

        self.assertEqual(missing_confirmation.status_code, 400)
        self.assertEqual(too_much.data["error"], "HEDERA_TESTNET_AMOUNT_MUST_BE_0_1_HBAR")
        self.assertEqual(unknown_milestone.status_code, 404)
        send_transfer.assert_not_called()
        self.assertEqual(SettlementRecord.objects.count(), 0)

    @patch(
        "command_center.views.submit_testnet_hbar_transfer",
        side_effect=HederaPaymentSubmissionError("HEDERA_TESTNET_TRANSFER_OUTCOME_UNKNOWN", outcome_unknown=True),
    )
    def test_uncertain_network_result_locks_the_milestone_against_duplicate_payment(self, send_transfer):
        payload = {"milestone_id": self.milestone.milestone_id, "amount_hbar": "0.1", "confirm": True}

        failed = self.client.post(self.transfer_path, payload, format="json")
        retry = self.client.post(self.transfer_path, payload, format="json")

        self.assertEqual(failed.status_code, 502)
        self.assertEqual(failed.data["error"], "HEDERA_TESTNET_TRANSFER_OUTCOME_UNKNOWN")
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(retry.data["error"], "HEDERA_MILESTONE_ALREADY_PAID")
        self.assertEqual(SettlementRecord.objects.get().status, SettlementRecord.Status.UNKNOWN)
        send_transfer.assert_called_once()
