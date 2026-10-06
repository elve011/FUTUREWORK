"""Mock adapters (FW_MODE=mock). Self-contained: no network, no other module."""
import base64
import logging

from .base import HcsError

log = logging.getLogger(__name__)
PUBLISHED: list = []  # envelopes "sent" to Dev 4 (inspect in tests / demos)


class MockLedger:
    """In-memory stand-in for HCS + Mirror Node, shared by MockHcs and MockMirror."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.topics = {}              # topic_id -> [messages]
        self.fail_next_submits = 0    # inject HCS outages
        self.mirror_lag_polls = 0     # inject Mirror Node delay (number of empty polls)

    def new_topic(self):
        topic_id = f"0.0.{1002 + len(self.topics)}"  # first topic == mock-data topic 0.0.1002
        self.topics[topic_id] = []
        return topic_id


LEDGER = MockLedger()


class MockProject:
    def get_milestone(self, project_id, milestone_id):
        return {"projectId": project_id, "milestoneId": milestone_id, "title": "Backend", "units": 30,
                "deadline": "2026-10-20"}


class MockGitHub:
    def ensure_webhook(self, full_name, callback_url):
        return {"id": 1, "existing": False}

    def fetch_activity(self, full_name, limit=20):
        import json
        from django.conf import settings
        names = [("push", "push.json"), ("pull_request", "pull_request_merged.json"), ("pull_request_review", "pull_request_review.json")]
        return [(ev, {**json.loads((settings.FIXTURES_DIR / f).read_text()), "repository": {"full_name": full_name}}, f"sync-{ev}")
                for ev, f in names]


class MockHcs:
    def create_topic(self, memo):
        return LEDGER.new_topic()

    def submit(self, topic_id, message):
        if LEDGER.fail_next_submits > 0:
            LEDGER.fail_next_submits -= 1
            raise HcsError("mock HCS unavailable")
        msgs = LEDGER.topics.setdefault(topic_id, [])
        seq = len(msgs) + 1
        msgs.append({"message": message, "consensusTimestamp": f"{1760000000 + seq}.000000001"})
        return {"sequenceNumber": seq, "transactionId": f"0.0.1234@{1760000000 + seq}.000000000"}


class MockMirror:
    def get_message(self, topic_id, sequence_number):
        if LEDGER.mirror_lag_polls > 0:
            LEDGER.mirror_lag_polls -= 1
            return None
        msgs = LEDGER.topics.get(topic_id, [])
        if 1 <= sequence_number <= len(msgs):
            m = msgs[sequence_number - 1]
            return {"message": m["message"], "consensusTimestamp": m["consensusTimestamp"],
                    "sequenceNumber": sequence_number}
        return None


class MockEvents:
    def publish(self, envelope):
        PUBLISHED.append(envelope)
        log.info("mock publish %s", envelope["type"])


class MockLLM:
    def review(self, features, milestone):
        return {"verdict": "consistent", "adjustment": 0, "notes": "mock llm: no anomaly"}


def b64(text: str) -> str:  # helper for tests
    return base64.b64encode(text.encode()).decode()
