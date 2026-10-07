"""Dependency-free smoke tests for the documented event contract.

Run with: python -m unittest discover -s tests/phase-01 -p 'test_*stdlib.py'
The JSON Schema remains the normative contract; this smoke suite checks its
important invariants without requiring the optional pytest/jsonschema packages.
"""

import json
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "docs" / "api-contracts" / "event.schema.json"


def sample_event():
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


class EventContractSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.required = set(cls.schema["required"])
        cls.properties = cls.schema["properties"]

    def is_valid(self, event):
        if not isinstance(event, dict) or not self.required.issubset(event):
            return False
        if self.schema.get("additionalProperties") is False and set(event) - set(self.properties):
            return False
        for key, value in event.items():
            rule = self.properties[key]
            if "enum" in rule and value not in rule["enum"]:
                return False
            expected = rule.get("type")
            types = expected if isinstance(expected, list) else [expected]
            if "string" in types and value is not None and not isinstance(value, str):
                return False
            if "object" in types and not isinstance(value, dict):
                return False
            if "date-time" == rule.get("format"):
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                except (AttributeError, ValueError):
                    return False
        return True

    def test_documented_event_is_valid(self):
        self.assertTrue(self.is_valid(sample_event()))

    def test_optional_contract_metadata_is_backward_compatible(self):
        event = sample_event()
        event.update(schema_version="1.1", producer_id="dev2")
        self.assertTrue(self.is_valid(event))

    def test_required_fields_are_enforced(self):
        event = sample_event()
        del event["event_id"]
        self.assertFalse(self.is_valid(event))

    def test_unknown_event_type_is_rejected(self):
        event = sample_event()
        event["event_type"] = "UNDECLARED_EVENT"
        self.assertFalse(self.is_valid(event))

    def test_invalid_timestamp_is_rejected(self):
        event = sample_event()
        event["occurred_at"] = "yesterday"
        self.assertFalse(self.is_valid(event))

    def test_caller_cannot_supply_trace_id(self):
        event = sample_event()
        event["trace_id"] = "caller-controlled"
        self.assertFalse(self.is_valid(event))

    def test_payload_must_be_an_object(self):
        event = sample_event()
        event["payload"] = "not-an-object"
        self.assertFalse(self.is_valid(event))


if __name__ == "__main__":
    unittest.main()
