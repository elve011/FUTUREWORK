"""Evidence sources used by Dev 4's deterministic verification agent.

GitHub is read-only. The adapter fetches every fact used by scoring itself;
caller-supplied commit/review/CI claims are ignored in github mode.
"""

import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings


class EvidenceSourceError(RuntimeError):
    """A source is unavailable or returned an invalid response."""

    def __init__(self, code):
        self.code = re.sub(r"[^A-Z0-9_]", "_", str(code).upper())[:64]
        super().__init__(self.code)


class LocalEvidenceAdapter:
    source = "LOCAL_TEST_ONLY"

    def fetch(self, evidence):
        return {
            "source": self.source,
            "commits": evidence.get("commits", []),
            "pull_requests": evidence.get("pull_requests", []),
            "reviews": evidence.get("reviews", []),
            "ci_status": evidence.get("ci_status", "PENDING"),
            "source_refs": ["local-fixture:" + evidence.get("evidence_id", "unknown")],
        }


class GitHubEvidenceAdapter:
    source = "GITHUB_API"
    API_ROOT = "https://api.github.com"
    USER_AGENT = "FUTUREWORK-Dev4-EvidenceAgent/1.0"
    REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    PAGE_SIZE = 100
    MAX_PAGES = 10

    def __init__(self, token, timeout=5):
        self.token = token or ""
        self.timeout = timeout
        self.deadline = None

    def _get(self, path):
        remaining = self.deadline - time.monotonic() if self.deadline is not None else self.timeout
        if remaining <= 0:
            raise EvidenceSourceError("GITHUB_EVIDENCE_TIME_BUDGET_EXCEEDED")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": self.USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = Request(self.API_ROOT + path, headers=headers)
        try:
            with urlopen(request, timeout=min(self.timeout, remaining)) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise EvidenceSourceError("GITHUB_RESPONSE_TOO_LARGE")
                return json.loads(body.decode("utf-8"))
        except HTTPError as exc:
            code = "GITHUB_RATE_LIMITED" if exc.code == 429 or (exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0") else f"GITHUB_HTTP_{exc.code}"
            raise EvidenceSourceError(code) from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise EvidenceSourceError("GITHUB_SOURCE_UNAVAILABLE") from None

    def _get_paginated(self, path, *, result_key=None, error_code):
        rows = []
        for page in range(1, self.MAX_PAGES + 1):
            page_path = path if page == 1 else f"{path}&page={page}"
            response = self._get(page_path)
            page_rows = response if result_key is None else response.get(result_key) if isinstance(response, dict) else None
            if not isinstance(page_rows, list):
                raise EvidenceSourceError(error_code)
            rows.extend(page_rows)
            if len(page_rows) < self.PAGE_SIZE:
                return rows
        raise EvidenceSourceError(error_code)

    def fetch(self, evidence):
        self.deadline = time.monotonic() + 20
        repository = evidence.get("repository", "")
        if not self.REPOSITORY_RE.fullmatch(repository):
            raise EvidenceSourceError("GITHUB_REPOSITORY_INVALID")
        if repository.lower() not in getattr(settings, "FW_GITHUB_ALLOWED_REPOSITORIES", set()):
            raise EvidenceSourceError("GITHUB_REPOSITORY_NOT_ALLOWLISTED")
        owner, repo = repository.split("/", 1)
        root = f"/repos/{owner}/{repo}"
        commits = []
        pull_requests = []
        reviews = []
        check_statuses = []
        source_refs = []

        commit_shas = evidence.get("commit_shas", [])
        pull_numbers = evidence.get("pull_request_numbers", [])
        if not commit_shas or not pull_numbers or len(commit_shas) > 10 or len(pull_numbers) > 10:
            raise EvidenceSourceError("GITHUB_EVIDENCE_REFERENCE_LIMIT_OR_MISSING")
        checked_shas = set()
        for sha in commit_shas:
            commit = self._get(f"{root}/commits/{sha}")
            author = (commit.get("author") or {}).get("login") or ""
            committer = (commit.get("committer") or {}).get("login") or ""
            commits.append({"sha": commit.get("sha", sha), "author_id": author, "committer_id": committer})
            source_refs.append(commit.get("html_url", f"https://github.com/{repository}/commit/{sha}"))
            checked_shas.add(sha)

        for number in pull_numbers:
            pr = self._get(f"{root}/pulls/{number}")
            author = (pr.get("user") or {}).get("login") or ""
            merged = pr.get("merged") is True
            pull_requests.append({
                "number": pr.get("number", number),
                "author_id": author,
                "state": "MERGED" if merged else str(pr.get("state", "open")).upper(),
                "head_sha": (pr.get("head") or {}).get("sha", ""),
            })
            source_refs.append(pr.get("html_url", f"https://github.com/{repository}/pull/{number}"))
            pr_commit_rows = self._get_paginated(
                f"{root}/pulls/{number}/commits?per_page={self.PAGE_SIZE}",
                error_code="GITHUB_PULL_REQUEST_COMMITS_INCOMPLETE",
            )
            pull_requests[-1]["commit_shas"] = [row.get("sha", "") for row in pr_commit_rows if row.get("sha")]
            review_rows = self._get_paginated(
                f"{root}/pulls/{number}/reviews?per_page={self.PAGE_SIZE}",
                error_code="GITHUB_REVIEWS_INCOMPLETE",
            )
            reviews.extend({
                "pull_request_number": number,
                "reviewer_id": (row.get("user") or {}).get("login", ""),
                "state": str(row.get("state", "COMMENTED")).upper(),
                "submitted_at": row.get("submitted_at") or "",
            } for row in review_rows)
            head_sha = (pr.get("head") or {}).get("sha")
            if head_sha:
                checked_shas.add(head_sha)

        for sha in checked_shas:
            runs = self._get_paginated(
                f"{root}/commits/{sha}/check-runs?per_page={self.PAGE_SIZE}",
                result_key="check_runs",
                error_code="GITHUB_CHECK_RUNS_INCOMPLETE",
            )
            if runs:
                states = [str(run.get("conclusion") or "PENDING").upper() for run in runs]
                check_statuses.append("FAILURE" if any(state not in {"SUCCESS", "NEUTRAL", "SKIPPED"} and state != "PENDING" for state in states) else ("PENDING" if "PENDING" in states else "SUCCESS"))
            else:
                combined_status = self._get(f"{root}/commits/{sha}/status")
                state = str(combined_status.get("state", "pending")).upper()
                check_statuses.append("SUCCESS" if state == "SUCCESS" else "FAILURE" if state in {"FAILURE", "ERROR"} else "PENDING")

        ci_status = "FAILURE" if "FAILURE" in check_statuses else ("PENDING" if not check_statuses or "PENDING" in check_statuses else "SUCCESS")
        return {
            "source": self.source,
            "repository": repository,
            "commits": commits,
            "pull_requests": pull_requests,
            "reviews": reviews,
            "ci_status": ci_status,
            "source_refs": list(dict.fromkeys(source_refs)),
        }


def get_evidence_adapter(mode="local"):
    if mode in {"local", "mock"}:
        return LocalEvidenceAdapter()
    if mode == "github":
        return GitHubEvidenceAdapter(getattr(settings, "FW_GITHUB_TOKEN", ""))
    raise EvidenceSourceError(f"EVIDENCE_MODE_UNSUPPORTED_{str(mode).upper()}")
