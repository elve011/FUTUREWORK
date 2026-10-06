"""Real adapters (FW_MODE=live)."""
import base64
import json
import logging
import subprocess

import requests
from django.conf import settings

from common.errors import ApiError
from .base import HcsError, LLMUnavailable

log = logging.getLogger(__name__)


class RealProject:
    """Dev 1 Project Contract: GET /api/projects/:id/contract"""

    def get_milestone(self, project_id, milestone_id):
        r = requests.get(f"{settings.PROJECT_API_URL}/api/projects/{project_id}/contract", timeout=10)
        r.raise_for_status()
        for m in r.json().get("milestones", []):
            if m["milestoneId"] == milestone_id:
                return {"projectId": project_id, **m}
        raise ApiError("MILESTONE_NOT_FOUND", f"{milestone_id} not found in {project_id}", 404)


class RealGitHub:
    def ensure_webhook(self, full_name, callback_url):
        r = requests.post(
            f"https://api.github.com/repos/{full_name}/hooks",
            headers={"Authorization": f"Bearer {settings.GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
            json={"name": "web", "active": True, "events": ["push", "pull_request", "pull_request_review"],
                  "config": {"url": callback_url, "content_type": "json", "secret": settings.GITHUB_WEBHOOK_SECRET}},
            timeout=15,
        )
        if r.status_code == 422:  # hook already exists
            return {"id": None, "existing": True}
        r.raise_for_status()
        return {"id": r.json()["id"], "existing": False}


    def fetch_activity(self, full_name, limit=20):
        """Pull recent commits / merged PRs / reviews from the GitHub API and shape them like webhook payloads."""
        h = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
        api = f"https://api.github.com/repos/{full_name}"
        get = lambda url, **kw: (lambda r: (r.raise_for_status(), r.json())[1])(requests.get(url, headers=h, timeout=20, **kw))
        repo_ref = {"full_name": full_name}
        branch = get(api)["default_branch"]
        commits = []
        for c in get(f"{api}/commits", params={"sha": branch, "per_page": limit}):
            d = get(f"{api}/commits/{c['sha']}")
            files = d.get("files", [])
            commits.append({
                "id": d["sha"], "message": d["commit"]["message"], "timestamp": d["commit"]["author"]["date"],
                "author": {"username": (d.get("author") or {}).get("login"), "name": d["commit"]["author"]["name"]},
                "added": [f["filename"] for f in files if f["status"] == "added"],
                "removed": [f["filename"] for f in files if f["status"] == "removed"],
                "modified": [f["filename"] for f in files if f["status"] not in ("added", "removed")],
            })
        out = [("push", {"ref": f"refs/heads/{branch}", "repository": repo_ref, "commits": commits}, f"sync-push-{branch}-{commits[0]['id'][:7] if commits else 'none'}")]
        for pr in get(f"{api}/pulls", params={"state": "closed", "per_page": limit}):
            if not pr.get("merged_at"):
                continue
            full = get(f"{api}/pulls/{pr['number']}")  # list endpoint lacks additions/deletions
            out.append(("pull_request", {"action": "closed", "repository": repo_ref, "pull_request": full}, f"sync-pr-{full['number']}"))
            for rv in get(f"{api}/pulls/{pr['number']}/reviews"):
                if rv.get("submitted_at"):
                    out.append(("pull_request_review", {"action": "submitted", "repository": repo_ref, "review": rv, "pull_request": full}, f"sync-review-{rv['id']}"))
        return out


class RealHcs:
    """Thin bridge to the Node SDK (hcs_bridge/*.mjs): same @hashgraph/sdk calls as the official examples."""

    def _run(self, script, *args):
        proc = subprocess.run(["node", script, *args], cwd=settings.HCS_BRIDGE_DIR, capture_output=True,
                              text=True, timeout=45)
        if proc.returncode != 0:
            raise HcsError(proc.stderr.strip() or "hcs bridge failed")
        return json.loads(proc.stdout)

    def create_topic(self, memo):
        return self._run("create_topic.mjs", memo)["topicId"]

    def submit(self, topic_id, message):
        return self._run("submit_message.mjs", topic_id, message)


class RealMirror:
    def get_message(self, topic_id, sequence_number):
        r = requests.get(f"{settings.MIRROR_NODE_URL}/api/v1/topics/{topic_id}/messages/{sequence_number}", timeout=10)
        if r.status_code == 404:
            return None  # not propagated yet
        r.raise_for_status()
        d = r.json()
        return {"message": base64.b64decode(d["message"]).decode(), "consensusTimestamp": d["consensus_timestamp"],
                "sequenceNumber": d["sequence_number"]}


class RealEvents:
    """Publish to Dev 4: POST /api/events/ingest. Failures never block the pipeline (caller catches)."""

    def publish(self, envelope):
        r = requests.post(f"{settings.AGENT_API_URL}/api/events/ingest", json=envelope, timeout=5)
        r.raise_for_status()


SYSTEM_PROMPT = (
    "You review software work evidence against a project milestone. Reply with ONLY a JSON object: "
    '{"verdict":"consistent"|"suspicious","adjustment":<integer -20..10>,"notes":"<max 300 chars>"}. '
    "Penalize evidence that looks unrelated to the milestone, padded, or auto-generated."
)


class RealLLM:
    """Anthropic Messages API via plain HTTP. Swap this class if you use another provider."""

    def review(self, features, milestone):
        if not settings.LLM_API_KEY or not settings.LLM_MODEL:
            raise LLMUnavailable("LLM_API_KEY / LLM_MODEL not set")
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": settings.LLM_API_KEY, "anthropic-version": "2023-06-01"},
            json={"model": settings.LLM_MODEL, "max_tokens": 300, "temperature": 0, "system": SYSTEM_PROMPT,
                  "messages": [{"role": "user", "content": json.dumps({"milestone": milestone, "evidence": features})}]},
            timeout=20,
        )
        r.raise_for_status()
        text = r.json()["content"][0]["text"].strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(text)
