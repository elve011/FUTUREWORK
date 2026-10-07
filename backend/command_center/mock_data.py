"""Deterministic standalone fixtures. No Dev 1–3 service is required."""

from .models import Agent


MOCK_AGENTS = (
    ("planner", "Planner Agent", ["engagement_analysis", "milestone_planning", "work_unit_allocation", "deadline_projection"], "planner/1.1-local"),
    ("evidence", "Evidence Verification Agent", ["github_commit_review_ci_readonly", "local_fixture_verification", "proof_hashing"], "evidence/1.1"),
    ("risk", "Risk & Policy Agent", ["evidence_link_validation", "explainable_risk_scoring", "allow_block_human_review"], "risk-policy/1.1-local"),
    ("settlement", "Settlement Monitoring Agent", ["settlement_state_machine", "hedera_observation", "finality_validation_no_signing"], "settlement-monitor/1.1-local"),
)


def ensure_mock_agents():
    """Upsert the four specification agents so a fresh database is demo-ready.

    Agent definitions belong to Dev 4's own registry and are independent of the
    selected mode for project, event, or Hedera data sources.
    """
    for key, display_name, capabilities, version in MOCK_AGENTS:
        Agent.objects.update_or_create(
            key=key,
            defaults={
                "display_name": display_name,
                "capabilities": capabilities,
                "agent_version": version,
            },
        )
