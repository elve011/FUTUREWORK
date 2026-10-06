"""Contract checks for the Dev 4 event-ingestion boundary."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "docs" / "api-contracts" / "event.schema.json"


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def valid_event():
    return {
        "event_id": "evt-001",
        "event_type": "MILESTONE_COMPLETED",
        "project_id": "FW-DEMO-001",
        "milestone_id": "milestone-02",
        "occurred_at": "2026-10-01T10:00:00Z",
        "source": "evidence-service",
        "payload": {},
        "correlation_id": "upstream-001",
    }


def test_accepts_documented_event(validator):
    assert validator.is_valid(valid_event())


def test_accepts_optional_versioned_envelope_without_breaking_legacy(validator):
    event = valid_event()
    event.update(schema_version="1.1", producer_id="dev2")
    assert validator.is_valid(event)


@pytest.mark.parametrize("missing", ["event_id", "event_type", "project_id", "occurred_at", "source", "payload"])
def test_rejects_missing_required_field(validator, missing):
    event = valid_event()
    del event[missing]
    assert not validator.is_valid(event)


def test_rejects_unknown_event_type(validator):
    event = valid_event()
    event["event_type"] = "PAYMENT_APPROVED_BY_MAGIC"
    assert not validator.is_valid(event)


def test_rejects_invalid_timestamp(validator):
    event = valid_event()
    event["occurred_at"] = "yesterday"
    assert not validator.is_valid(event)


def test_rejects_uncontracted_fields(validator):
    event = valid_event()
    event["trace_id"] = "caller-controlled"
    assert not validator.is_valid(event)


def test_schema_does_not_allow_arbitrary_non_object_payload(validator):
    event = valid_event()
    event["payload"] = "not-an-object"
    assert not validator.is_valid(event)
