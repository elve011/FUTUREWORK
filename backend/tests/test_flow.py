import hashlib
import hmac
import json

import pytest

from domain.canonical import proof_hash
from evidence.models import Evidence
from hcs.models import HCSEvent
from ports.mock import LEDGER, PUBLISHED

pytestmark = pytest.mark.django_db
FIX = "../contracts/fixtures/github/"


def load(name):
    from django.conf import settings
    return json.loads((settings.FIXTURES_DIR / name).read_text())


def send(client, event, payload, delivery, secret="test-secret"):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/evidence/github/webhook", data=body, content_type="application/json",
                       HTTP_X_GITHUB_EVENT=event, HTTP_X_GITHUB_DELIVERY=delivery, HTTP_X_HUB_SIGNATURE_256=sig)


@pytest.fixture
def connected(client):
    r = client.post("/api/evidence/github/connect", {"projectId": "FW-DEMO-001", "repoFullName": "demo-org/demo-repo",
                                                      "workerGithub": "demo-worker"}, format="json")
    assert r.status_code == 201


def test_push_verifies_one_rejects_one_and_anchors_on_hcs(client, connected):
    r = send(client, "push", load("push.json"), "d-1")
    assert r.status_code == 202 and r.json()["status"] == "processed"

    good = Evidence.objects.get(source_ref__startswith="a1b2c3d")
    bad = Evidence.objects.get(source_ref__startswith="b2c3d4e")
    assert good.status == "ANCHORED" and bad.status == "REJECTED"
    assert good.latest_verification().score >= 60 > bad.latest_verification().score

    # exactly one HCS message, containing the same hash as our reproducible Proof Hash
    assert len(LEDGER.topics["0.0.1002"]) == 1
    sent = json.loads(LEDGER.topics["0.0.1002"][0]["message"])
    assert sent["h"] == proof_hash(good.hashable()) == good.proof.proof_hash
    ev = HCSEvent.objects.get()
    assert ev.status == "CONFIRMED" and ev.readback_ok and ev.consensus_timestamp

    types = [e["type"] for e in PUBLISHED]
    assert types.count("EVIDENCE_COLLECTED") == 2
    assert "EVIDENCE_VERIFIED" in types and "EVIDENCE_REJECTED" in types and "HCS_EVENT_SUBMITTED" in types


def test_duplicate_delivery_is_ignored(client, connected):
    send(client, "push", load("push.json"), "d-1")
    r = send(client, "push", load("push.json"), "d-1")
    assert r.json()["status"] == "duplicate"
    assert Evidence.objects.count() == 2 and len(LEDGER.topics["0.0.1002"]) == 1


def test_same_commits_redelivered_with_new_id_do_not_double_anchor(client, connected):
    send(client, "push", load("push.json"), "d-1")
    r = send(client, "push", load("push.json"), "d-2")
    assert r.json()["evidence"] == []
    assert len(LEDGER.topics["0.0.1002"]) == 1


def test_bad_signature_rejected(client, connected):
    r = send(client, "push", load("push.json"), "d-1", secret="wrong")
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert Evidence.objects.count() == 0


def test_evidence_contract_matches_spec_shape(client, connected):
    send(client, "push", load("push.json"), "d-1")
    send(client, "pull_request", load("pull_request_merged.json"), "d-2")
    send(client, "pull_request_review", load("pull_request_review.json"), "d-3")
    r = client.get("/api/evidence/milestones/M-DEMO-001/contract")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"projectId", "milestoneId", "evidenceId", "verified", "complianceScore", "proofHash",
                         "githubCommit", "topicId", "sequenceNumber", "consensusTimestamp"}
    assert body["verified"] is True and body["topicId"] == "0.0.1002" and body["proofHash"].startswith("sha256:")
    assert client.get("/api/evidence/milestones/M-999/contract").status_code == 404
    assert client.get("/api/evidence/github/pulls").json()[0]["number"] == 7
    assert client.get("/api/evidence/github/reviews").json()[0]["state"] == "approved"


def test_unattached_evidence_is_flagged_then_attached_manually(client, connected):
    payload = load("push.json")
    payload["ref"] = "refs/heads/main"
    payload["commits"] = payload["commits"][:1]
    payload["commits"][0]["message"] = "feat(evidence): add webhook signature verification"
    send(client, "push", payload, "d-9")
    ev = Evidence.objects.get()
    assert ev.status == "COLLECTED" and not ev.attached
    assert client.get("/api/evidence?unattached=1").json()[0]["attached"] is False

    r = client.post(f"/api/evidence/{ev.evidence_id}/verify")
    assert r.status_code == 409 and r.json()["error"]["code"] == "EVIDENCE_NOT_ATTACHED"

    r = client.post(f"/api/evidence/{ev.evidence_id}/attach", {"milestoneId": "m-002"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "ANCHORED" and r.json()["milestoneId"] == "M-002"


def test_hcs_outage_queues_then_sync_recovers(client, connected):
    LEDGER.fail_next_submits = 3  # == HCS_MAX_RETRIES -> first attempt round fails
    send(client, "push", load("push.json"), "d-1")
    good = Evidence.objects.get(source_ref__startswith="a1b2c3d")
    assert good.status == "VERIFIED"  # verified but not anchored yet
    assert HCSEvent.objects.get().status == "QUEUED"

    r = client.post("/api/hcs/sync")
    assert r.status_code == 200 and r.json()["resubmitted"] == 1
    good.refresh_from_db()
    assert good.status == "ANCHORED" and HCSEvent.objects.get().status == "CONFIRMED"
    assert len(LEDGER.topics["0.0.1002"]) == 1  # no duplicate


def test_mirror_lag_leaves_submitted_then_sync_confirms(client, connected):
    LEDGER.mirror_lag_polls = 5  # == MIRROR_POLL_ATTEMPTS
    send(client, "push", load("push.json"), "d-1")
    assert HCSEvent.objects.get().status == "SUBMITTED"
    client.post("/api/hcs/sync")
    e = HCSEvent.objects.get()
    assert e.status == "CONFIRMED" and e.consensus_timestamp


def test_llm_garbage_falls_back_to_rules(client, connected, monkeypatch):
    from ports import mock
    monkeypatch.setattr(mock.MockLLM, "review", lambda self, f, m: {"verdict": "banana", "adjustment": 999})
    send(client, "push", load("push.json"), "d-1")
    good = Evidence.objects.get(source_ref__startswith="a1b2c3d")
    assert good.latest_verification().method == "rules" and good.status == "ANCHORED"


def test_error_format_and_overview(client, connected):
    r = client.post("/api/evidence/github/connect", {"projectId": "FW-1"}, format="json")
    assert r.status_code == 400 and set(r.json()["error"]) == {"code", "message", "details", "traceId"}
    send(client, "push", load("push.json"), "d-1")
    o = client.get("/api/evidence/overview?projectId=FW-DEMO-001").json()
    assert o["total"] == 2 and o["byStatus"] == {"ANCHORED": 1, "REJECTED": 1} and o["averageScore"] is not None
    assert client.get("/health").json()["status"] == "ok"


def test_manual_evidence_is_idempotent(client):
    body = {"projectId": "FW-DEMO-001", "milestoneId": "M-DEMO-001", "title": "Signed design document v2",
            "author": "demo-worker", "content": "hello"}
    assert client.post("/api/evidence", body, format="json").status_code == 201
    assert client.post("/api/evidence", body, format="json").status_code == 200
    assert Evidence.objects.count() == 1


def test_github_backfill_uses_same_pipeline_and_is_idempotent(client, connected):
    r = client.post("/api/evidence/github/sync", {"projectId": "FW-DEMO-001"}, format="json")
    assert r.status_code == 200 and r.json()["processed"] == 3 and len(r.json()["evidence"]) == 4
    again = client.post("/api/evidence/github/sync", {"projectId": "FW-DEMO-001"}, format="json").json()
    assert again["processed"] == 0 and again["duplicates"] == 3
    assert Evidence.objects.count() == 4
    assert client.post("/api/evidence/github/sync", {"projectId": "FW-NOPE"}, format="json").status_code == 404


def test_hashscan_transaction_url(client, connected):
    send(client, "push", load("push.json"), "d-1")
    ev = client.get("/api/hcs/events").json()[0]
    assert ev["transactionUrl"] == "https://hashscan.io/testnet/transaction/0.0.1234-1760000001-000000000"
