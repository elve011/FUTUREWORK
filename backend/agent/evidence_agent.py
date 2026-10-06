"""Evidence Verification Agent (LangGraph): score_rules -> llm_review -> decide.

The LLM can only nudge the deterministic score (-20..+10) and never overrides hard blockers.
If the LLM is down or returns invalid JSON, the deterministic score stands (spec: repli deterministe).
"""
import logging
from typing import TypedDict

from domain.scoring import score_evidence
from ports.factory import get_port

log = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    features: dict
    milestone: dict
    threshold: int
    score: int
    reasons: list
    blockers: list
    llm: dict
    method: str
    verdict: str


def validate_llm_output(out) -> dict:
    if not isinstance(out, dict):
        raise ValueError("LLM output is not an object")
    if out.get("verdict") not in ("consistent", "suspicious"):
        raise ValueError("bad verdict")
    adj = out.get("adjustment")
    if isinstance(adj, bool) or not isinstance(adj, int) or not -20 <= adj <= 10:
        raise ValueError("bad adjustment")
    notes = out.get("notes", "")
    if not isinstance(notes, str):
        raise ValueError("bad notes")
    return {"verdict": out["verdict"], "adjustment": adj, "notes": notes[:500]}


def score_rules(state: AgentState) -> dict:
    r = score_evidence(state["features"])
    return {"score": r.score, "reasons": r.reasons, "blockers": r.blockers, "method": "rules"}


def llm_review(state: AgentState) -> dict:
    if state.get("blockers"):  # nothing to gain: already blocked
        return {"llm": None}
    try:
        out = validate_llm_output(get_port("llm").review(state["features"], state["milestone"]))
        return {"llm": out, "method": "rules+llm"}
    except Exception as exc:  # network, invalid JSON, missing key...
        log.warning("LLM unavailable, deterministic fallback: %s", exc)
        return {"llm": None}


def decide(state: AgentState) -> dict:
    reasons, score = list(state["reasons"]), state["score"]
    llm = state.get("llm")
    if llm:
        score = max(0, min(100, score + llm["adjustment"]))
        reasons.append({"code": "LLM_REVIEW", "points": llm["adjustment"], "max": 10,
                        "detail": f"{llm['verdict']}: {llm['notes']}"})
    ok = not state["blockers"] and score >= state["threshold"]
    return {"score": score, "reasons": reasons, "verdict": "VERIFIED" if ok else "REJECTED"}


NODES = [("score_rules", score_rules), ("llm_review", llm_review), ("decide", decide)]


def run(state: AgentState) -> AgentState:
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:  # langgraph not installed: same nodes, plain loop
        for _, fn in NODES:
            state = {**state, **fn(state)}
        return state
    g = StateGraph(AgentState)
    for name, fn in NODES:
        g.add_node(name, fn)
    g.set_entry_point("score_rules")
    g.add_edge("score_rules", "llm_review")
    g.add_edge("llm_review", "decide")
    g.add_edge("decide", END)
    return g.compile().invoke(state)
