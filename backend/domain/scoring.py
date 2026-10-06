"""Deterministic compliance scoring (FR-E-05). This is also the agent's fallback when the LLM is down."""
from dataclasses import dataclass, field


@dataclass
class ScoreResult:
    score: int
    reasons: list = field(default_factory=list)
    blockers: list = field(default_factory=list)


def score_evidence(f: dict) -> ScoreResult:
    """
    features: attached(bool), author_ok(True/False/None), lines_changed(int|None),
              tests_touched(True/False/None), message_ok(bool), reviewed_or_merged(bool),
              ci_status('success'|'failure'|'pending'|None)
    Max 100. None = unknown -> neutral (about half the points).
    """
    reasons, blockers, total = [], [], 0

    def add(code, pts, mx, detail):
        nonlocal total
        total += pts
        reasons.append({"code": code, "points": pts, "max": mx, "detail": detail})

    if f.get("attached"):
        add("MILESTONE_LINKED", 25, 25, "Activity is linked to a milestone")
    else:
        add("MILESTONE_LINKED", 0, 25, "No milestone tag found")
        blockers.append("NOT_ATTACHED")

    author_ok = f.get("author_ok")
    if author_ok is True:
        add("AUTHOR", 15, 15, "Author matches the assigned worker")
    elif author_ok is None:
        add("AUTHOR", 8, 15, "Author not checked / unknown")
    else:
        add("AUTHOR", 0, 15, "Author is not the assigned worker")
        blockers.append("AUTHOR_MISMATCH")

    lines = f.get("lines_changed")
    if lines is None:
        add("SIZE", 8, 15, "Change size unknown")
    elif lines == 0:
        add("SIZE", 0, 15, "Empty change")
    elif lines > 1500:
        add("SIZE", 5, 15, f"Very large change ({lines} lines): hard to review")
    else:
        add("SIZE", 15, 15, f"Reasonable change size ({lines} lines)")

    tests = f.get("tests_touched")
    add("TESTS", 15 if tests else 7 if tests is None else 0, 15,
        {True: "Tests touched", None: "Tests unknown", False: "No test changes"}[tests if tests is None else bool(tests)])

    add("MESSAGE", 10 if f.get("message_ok") else 0, 10,
        "Descriptive message" if f.get("message_ok") else "Missing or generic message")

    peer = bool(f.get("reviewed_or_merged"))
    add("REVIEW", 10 if peer else 0, 10, "Reviewed / merged" if peer else "Not reviewed or merged")

    ci = f.get("ci_status")
    add("CI", 10 if ci == "success" else 0 if ci == "failure" else 5, 10, f"CI status: {ci or 'unknown'}")

    return ScoreResult(score=min(100, total), reasons=reasons, blockers=blockers)
