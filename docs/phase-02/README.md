# Phase 2 — Backend foundation

## Delivered

- Standalone Django + Django REST Framework project using SQLite/Django ORM.
- Data models for `Agent`, `AgentTask`, `AgentExecution`, `AgentAction`, `AgentDecision`, `AgentAlert`, `SystemEvent`, `AuditLog`, `Notification`, and `DashboardMetric`.
- Four deterministic agent registry definitions: Planner, Evidence, Risk and Settlement.
- Health, agent registry/status, agent actions/history, event ingestion, project activity/alerts/metrics/dashboard, Hedera activity/transactions, and OpenAPI endpoints.
- Event envelope validation, server-generated trace ID, idempotent retry handling, collision conflict (`409`), and append-only initial audit entry.
- Compiled LangGraph workflow invoked from ingestion: event routing, conservative policy gate, agent execution/action/decision persistence, and alert creation.
- Critical settlement requests default to `HUMAN_REVIEW`; this backend does not initiate or sign payments.
- Recursive credential-like payload redaction before storage, with original-payload SHA-256 used only for idempotency/integrity checks.
- Independent source mode settings for project, events and Hedera; mock is the default.
- Isolated mock project and Mirror Node adapters with `FW-DEMO-001` fixture data, HCS/HTS/contract/scheduled transaction examples, and provenance labels.
- Local four-event demo catalogue tagged as pending confirmation against the shared API Contracts catalogue.
- No Celery and no dependency on Dev 1–3.

## Endpoint behavior

| Endpoint | Behavior |
|---|---|
| `GET /healthz` | Service liveness response. |
| `GET /api/agents` | Four registry agents and their current status/capabilities. |
| `GET /api/agents/status` | Agent status projection. |
| `GET /api/agents/actions` | Agent action stream, filterable by agent and project. |
| `GET /api/agents/{id}/history` | Merged action, decision and execution history for one agent. |
| `POST /api/events/ingest` | Validate and persist one event; generate trace and initial audit. |
| `GET /api/projects/{id}/activity` | Project events and agent activity timeline. |
| `GET /api/projects/{id}/alerts` | Active alerts by project (`?active=false` includes resolved entries). |
| `GET /api/projects/{id}/metrics` | Mock project metrics plus stored historical measurements. |
| `GET /api/projects/{id}/hedera/activity` | Mirror Node fixture activity for HCS, HTS, contract and scheduled transaction records. |
| `GET /api/projects/{id}/hedera/transactions` | Mock transaction status and HashScan links. |
| `GET /api/projects/{id}/dashboard` | Project snapshot, agents, recent activity, alerts, and Hedera feed. |
| `GET /api/openapi` | DRF-generated OpenAPI schema. |

Event ingestion returns `202` on first acceptance, `200` for a matching retry, `409` if an existing `event_id` is reused with a different envelope, and `400` for invalid input. The request schema is documented under `docs/api-contracts`.

## Verification

Run the Django suite with `python backend/manage.py test command_center -v 2`. It checks the registry, health, ingestion, duplicate handling, malformed envelope rejection, trace/audit creation, redaction, all four demo routes and six alert fixtures under the 10-second acceptance limit. Run the phase-1 contract smoke tests with `python -m unittest discover -s tests/phase-01 -p 'test_*stdlib.py' -v`.

## Next implementation slice

Next, complete the backend lifecycle that is currently only scaffolded: settlement state transitions and the no-Celery polling command, human policy review, then the live Mirror Node adapter. The event catalogue also needs confirmation against the shared API Contracts document.
