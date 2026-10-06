"""Canonical JSON + Proof Hash (FR-E-06). Pure Python, no Django."""
import hashlib
import json

# Only stable fields are hashed: no DB ids, no generated timestamps, no scores.
HASHED_FIELDS = ("projectId", "milestoneId", "source", "sourceRef", "author", "contentDigest", "occurredAt")


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_digest(obj_or_text) -> str:
    text = obj_or_text if isinstance(obj_or_text, str) else canonical_json(obj_or_text)
    return "sha256:" + sha256_hex(text)


def proof_hash(evidence: dict) -> str:
    stable = {k: evidence[k] for k in HASHED_FIELDS}  # KeyError if a field is missing: on purpose
    return "sha256:" + sha256_hex(canonical_json(stable))
