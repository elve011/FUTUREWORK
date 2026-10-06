"""Ports = the API contract of each external dependency. Business code only talks to these."""
from typing import Protocol


class ProjectPort(Protocol):
    def get_milestone(self, project_id: str, milestone_id: str) -> dict: ...  # {projectId, milestoneId, title, units, deadline}


class GitHubPort(Protocol):
    def ensure_webhook(self, full_name: str, callback_url: str) -> dict: ...
    def fetch_activity(self, full_name: str, limit: int = 20) -> list: ...  # [(event_type, payload, delivery_id)]


class HcsPort(Protocol):
    def create_topic(self, memo: str) -> str: ...
    def submit(self, topic_id: str, message: str) -> dict: ...  # {sequenceNumber, transactionId}


class MirrorPort(Protocol):
    def get_message(self, topic_id: str, sequence_number: int): ...  # {message, consensusTimestamp, sequenceNumber} | None


class EventPort(Protocol):
    def publish(self, envelope: dict) -> None: ...


class LLMPort(Protocol):
    def review(self, features: dict, milestone: dict) -> dict: ...  # {verdict, adjustment, notes}


class HcsError(Exception):
    pass


class LLMUnavailable(Exception):
    pass
