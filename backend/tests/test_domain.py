from domain.canonical import canonical_json, proof_hash
from domain.milestone_tag import resolve_milestone
from domain.scoring import score_evidence
from githubint.security import valid_signature

BASE = {"projectId": "FW-001", "milestoneId": "M-002", "source": "COMMIT", "sourceRef": "abc",
        "author": "dev", "contentDigest": "sha256:1", "occurredAt": "2026-10-12T10:00:00Z"}


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1}) == '{"a":2,"b":1}'


def test_proof_hash_reproducible_and_ignores_volatile_fields():
    h = proof_hash(BASE)
    assert h.startswith("sha256:") and len(h) == 71
    assert proof_hash({**BASE, "score": 99, "db_id": 5, "created_at": "now"}) == h
    assert proof_hash({**BASE, "author": "someone-else"}) != h


def test_milestone_tag_priority_and_formats():
    assert resolve_milestone(labels=["milestone:M-002"], branch="feat/M-003-x") == ("M-002", "label")
    assert resolve_milestone(branch="feat/m-003-api") == ("M-003", "branch")
    assert resolve_milestone(title="[M-DEMO-001] thing") == ("M-DEMO-001", "title")
    assert resolve_milestone(message="no tag here, but ham-002 is not a tag") == (None, None)


def test_scoring_blockers_and_bounds():
    good = {"attached": True, "author_ok": True, "lines_changed": 200, "tests_touched": True,
            "message_ok": True, "reviewed_or_merged": True, "ci_status": "success"}
    assert score_evidence(good).score == 100
    bad_author = score_evidence({**good, "author_ok": False})
    assert "AUTHOR_MISMATCH" in bad_author.blockers
    assert "NOT_ATTACHED" in score_evidence({**good, "attached": False}).blockers


def test_webhook_signature():
    import hashlib, hmac
    sig = "sha256=" + hmac.new(b"s", b"body", hashlib.sha256).hexdigest()
    assert valid_signature("s", b"body", sig)
    assert not valid_signature("s", b"body2", sig)
    assert not valid_signature("s", b"body", "")
