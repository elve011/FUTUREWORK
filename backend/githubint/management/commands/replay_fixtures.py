"""Demo / dev helper: connect FW-DEMO-001's repo and replay recorded webhook payloads through the real pipeline."""
import json
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand

from githubint.models import GitHubRepository
from githubint.services import handle_delivery

ORDER = [("push", "push.json"), ("pull_request", "pull_request_merged.json"),
         ("pull_request_review", "pull_request_review.json")]


class Command(BaseCommand):
    help = "Replay contracts/fixtures/github/*.json through the ingestion pipeline"

    def handle(self, *args, **opts):
        GitHubRepository.objects.update_or_create(
            full_name="demo-org/demo-repo", defaults={"project_id": "FW-DEMO-001", "worker_github": "demo-worker"})
        for event, name in ORDER:
            payload = json.loads((settings.FIXTURES_DIR / name).read_text())
            res = handle_delivery(f"replay-{uuid.uuid4().hex[:8]}", event, payload)
            self.stdout.write(f"{event:22s} -> {res}")
