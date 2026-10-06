"""GitHub webhook payload -> normalized evidence dicts (FR-E-04). Pure functions."""
import re

from .canonical import content_digest
from .milestone_tag import resolve_milestone

TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|(_test|\.test|\.spec)\.[A-Za-z0-9]+$|(^|/)test_[^/]+$", re.I)
GENERIC_MSG = re.compile(r"^\s*(wip|fix|fixes|update|updates|test|tests|change|changes|misc|\.+)\s*$", re.I)


def _first_line(text):
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def _message_ok(text):
    line = _first_line(text)
    return len(line) >= 10 and not GENERIC_MSG.match(line)


def _labels(pr):
    return [l.get("name", "") for l in pr.get("labels") or []]


def normalize_push(payload):
    branch = (payload.get("ref") or "").removeprefix("refs/heads/")
    out = []
    for c in payload.get("commits") or []:
        files = (c.get("added") or []) + (c.get("removed") or []) + (c.get("modified") or [])
        a = c.get("author") or {}
        msg = c.get("message", "")
        ms, how = resolve_milestone(branch=branch, message=msg)
        out.append({
            "source": "COMMIT", "source_ref": c["id"],
            "author": a.get("username") or a.get("name") or "unknown",
            "occurred_at": c["timestamp"], "title": _first_line(msg), "branch": branch,
            "milestone_id": ms, "milestone_source": how,
            "content_digest": content_digest({"sha": c["id"], "message": msg}),
            "metadata": {
                "files_changed": len(files), "additions": None, "deletions": None,
                "tests_touched": any(TEST_PATH.search(f) for f in files) if files else None,
                "message_ok": _message_ok(msg), "reviewed_or_merged": False, "ci_status": None,
                "branch": branch,
            },
        })
    return out


def normalize_pull_request(payload):
    pr = payload.get("pull_request") or {}
    if not (payload.get("action") == "closed" and pr.get("merged")):
        return []  # only merged PRs become evidence
    repo = payload["repository"]["full_name"]
    branch = (pr.get("head") or {}).get("ref", "")
    ms, how = resolve_milestone(labels=_labels(pr), branch=branch, title=pr.get("title", ""), message=pr.get("body") or "")
    return [{
        "source": "PULL_REQUEST", "source_ref": f"{repo}#{pr['number']}",
        "author": (pr.get("user") or {}).get("login", "unknown"),
        "occurred_at": pr.get("merged_at") or pr["updated_at"], "title": pr.get("title", ""), "branch": branch,
        "milestone_id": ms, "milestone_source": how,
        "content_digest": content_digest({"number": pr["number"], "title": pr.get("title"),
                                          "additions": pr.get("additions"), "deletions": pr.get("deletions"),
                                          "merge_commit_sha": pr.get("merge_commit_sha")}),
        "metadata": {
            "files_changed": pr.get("changed_files"), "additions": pr.get("additions"), "deletions": pr.get("deletions"),
            "tests_touched": None, "message_ok": _message_ok(pr.get("title")), "reviewed_or_merged": True,
            "ci_status": None, "branch": branch, "merge_commit_sha": pr.get("merge_commit_sha"),
            "number": pr["number"], "labels": _labels(pr),
        },
    }]


def normalize_review(payload):
    review, pr = payload.get("review") or {}, payload.get("pull_request") or {}
    if payload.get("action") != "submitted" or not review:
        return []
    repo = payload["repository"]["full_name"]
    branch = (pr.get("head") or {}).get("ref", "")
    ms, how = resolve_milestone(labels=_labels(pr), branch=branch, title=pr.get("title", ""))
    state = (review.get("state") or "").lower()
    return [{
        "source": "REVIEW", "source_ref": f"{repo}#{pr['number']}/review/{review['id']}",
        "author": (review.get("user") or {}).get("login", "unknown"),
        "occurred_at": review["submitted_at"], "title": f"Review ({state}) on PR #{pr['number']}", "branch": branch,
        "milestone_id": ms, "milestone_source": how,
        "content_digest": content_digest({"review_id": review["id"], "state": state, "body": review.get("body")}),
        "metadata": {
            "files_changed": None, "additions": None, "deletions": None, "tests_touched": None,
            "message_ok": _message_ok(review.get("body")), "reviewed_or_merged": state == "approved",
            "ci_status": None, "branch": branch, "number": pr["number"], "state": state,
        },
    }]
