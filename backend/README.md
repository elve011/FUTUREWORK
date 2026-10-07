# FUTUREWORK Dev 4 backend

Standalone Django REST backend for the AI Command Center & Monitoring mini-project.

## Prerequisites

- Python 3.11 or newer.
- Install the packages from `requirements.txt` in a virtual environment.

## Run locally (PowerShell from the repository root)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python backend\manage.py migrate
python backend\manage.py runserver
```

The first request to `/api/agents` seeds the four Dev 4 registry entries. `GET /healthz` is the liveness endpoint. The API is JSON-only and the standalone mock mode requires no Dev 1, Dev 2, Dev 3, Hedera credentials, or Celery. `backend/.env.example` is a variable reference; set any overrides in the process environment because no `.env` file loader is configured.

## Endpoints implemented in this phase

- `GET /healthz`
- `GET /api/agents`
- `GET /api/agents/status`
- `GET /api/agents/actions?agent=&project_id=`
- `GET /api/agents/{id}/history`
- `GET /api/settlements?project_id=&status=&limit=&offset=`
- `GET /api/settlements/{settlement_id}`
- `POST /api/events/ingest`
- `GET /api/projects/{id}/activity`
- `GET /api/projects/{id}/alerts`
- `GET /api/projects/{id}/metrics`
- `GET /api/projects/{id}/hedera/activity`
- `GET /api/projects/{id}/hedera/transactions`
- `GET /api/projects/{id}/dashboard`
- `GET /api/openapi`

## Durable workers

The event worker executes the versioned local Planner, Evidence, Risk & Policy, and Settlement Monitor contracts:

```powershell
python backend\manage.py process_events --once
```

The settlement poller is a separate read-only process. It records source-unavailable attempts without changing a settlement to confirmed:

```powershell
python backend\manage.py monitor_settlements --once
```

For a supervised local run, start one `process_events` worker and one `monitor_settlements` process. No Celery or broker is used. Phase 5 details and event semantics are documented in [`../docs/phase-05/README.md`](../docs/phase-05/README.md).

The full required API inventory and next endpoints are tracked in [`../docs/phase-01/requirements.md`](../docs/phase-01/requirements.md).

### Event ingestion

The request body follows [`../docs/api-contracts/event.schema.json`](../docs/api-contracts/event.schema.json). First acceptance returns `202` with the generated `trace_id` and synchronous workflow result; an identical retry returns `200` with the original trace; reuse of an `event_id` with a different envelope returns `409`. Invalid envelopes return `400`. LangGraph routes the event, applies the conservative policy gate, then persists its execution, action, decision and audit records in the same database transaction.

Credential-like values nested in payloads are redacted before persistence. A SHA-256 digest of the original payload is kept for integrity comparison. The original payload and the digest are not returned by the endpoint. A `SETTLEMENT_REQUESTED` event is held for `HUMAN_REVIEW`; this monitor does not authorize, sign or submit a payment.

## Modes

Modes are set independently per source with `FW_MODE_PROJECT`, `FW_MODE_EVENTS`, `FW_MODE_HEDERA`, `FW_MODE_SETTLEMENT`, and `FW_MODE_EVIDENCE`. Evidence defaults to `local` (synthetic input). To read GitHub evidence, configure `FW_MODE_EVIDENCE=github` and `FW_GITHUB_ALLOWED_REPOSITORIES=owner/repository`. Public allowlisted repositories can be read anonymously; an optional read-only `FW_GITHUB_TOKEN` is supported for private repositories or higher API limits. GitHub requests run as read-only GETs in the durable worker, not during HTTP ingestion. If the source cannot verify a submitted reference, its evidence status is `UNKNOWN` with a normalized reason code, never `VERIFIED`; see [`../docs/phase-05/agent-workflows.md`](../docs/phase-05/agent-workflows.md).

The local fixture workflow is documented in [`../docs/phase-05/agent-workflows.md`](../docs/phase-05/agent-workflows.md). Its synthetic ALLOW is only an end-to-end simulation: policy inputs still require a trusted producer and the settlement monitor never signs or submits a transaction.

For the wallet scenario, run `python backend\manage.py seed_hedera_demo` with `DEBUG=True`. It creates an isolated `DEMO_ONLY` account and project linked to the public test repository `elve011/repo-test`, with three completed milestones, 100 completed work units, verified `TEST_ONLY` evidence, and fixture approvals. The command emits the new account's password once. Set `FW_MODE_EVIDENCE=github` and allowlist `elve011/repo-test` to fetch real commits, pull requests, reviews, and CI results through GitHub's read-only API. The demo `elve011` profile login is unverified and cannot establish contributor identity. With a new, uncompromised ECDSA key configured only in the backend process environment, this account can send one real 0.1 HBAR transfer per eligible milestone on Hedera **testnet**. Transfers are submitted by the official Hiero Python SDK; no private key reaches the frontend. They are never enabled outside `DEBUG=True` and `FW_HEDERA_NETWORK=testnet`. A receipt with `SUCCESS` is recorded as `SUBMITTED_BY_OWNER`; the Mirror Node monitor remains responsible for separate observation.

### Hedera Mirror Node (read-only)

The observer uses the public Mirror Node REST API and never needs an operator key, account private key, SDK signer, or transaction submission permission. Set `FW_MODE_HEDERA=live`, keep `FW_HEDERA_NETWORK=testnet` while validating, and map each local project ID to only the account/topic/token/contract IDs explicitly approved for it in `FW_HEDERA_PROJECT_REFERENCES` (JSON). An unmapped project produces no Hedera observations; no fuzzy matching is used. `FW_HEDERA_MIRROR_NODE_URL` optionally overrides the HTTPS network API base and must end in `/api/v1`. Pagination is capped and reports an unavailable source rather than presenting truncated results as complete; transient network failures get one retry, successful HTTP responses are cached briefly, and source failures are exposed as HTTP 503 / `UNAVAILABLE`.

See [`../docs/phase-11/README.md`](../docs/phase-11/README.md) for account setup, exact environment configuration, testnet validation, and mainnet prerequisites.

## Tests

```powershell
python backend\manage.py test command_center -v 2
python -m unittest discover -s tests\phase-01 -p "test_*stdlib.py" -v
python -m pip install -r backend\requirements-dev.txt
python -m pytest tests\phase-01 -q
```

The first command covers API behavior, idempotency, trace/audit creation, event routing, policy gating, six alert categories, payload redaction, and deterministic project/Hedera fixtures. The second runs dependency-free phase-1 contract checks. The final commands install and run the JSON Schema validation suite.
