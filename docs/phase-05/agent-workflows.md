# Dev 4 agent workflow implementation

This document describes the local agent rules and the optional, read-only GitHub evidence source. These rules are Dev 4 standalone behavior; they do not replace Dev 1's Planner, Dev 2's official evidence score, or Dev 3's approved Risk & Policy contract.

## Event sequence

Use `schema_version: "dev4-local/1.0"` for the provisional standalone contracts. Set one `correlation_id` across every event in a workflow. The fixture `backend/command_center/fixtures/phase1_5_workflows.json` contains two synthetic scenarios and is loaded only by tests; there is no command that seeds it into the application database.

1. `ENGAGEMENT_CREATED` sends an agreement ID, title, total hours and total work units. Optional ISO dates set the planning window.
2. `EVIDENCE_REVIEW_REQUESTED` sends an evidence/work ID and contributor. Local mode carries synthetic commits, pull requests, reviews and CI status. GitHub mode carries an allowlisted `owner/repository`, GitHub login, commit SHAs and PR numbers.
3. `SETTLEMENT_REQUESTED` opens a local observation record. It does not create or sign a payment.
4. `POLICY_EVALUATION_REQUESTED` references both the Planner event ID and Evidence event ID, and includes milestone completion, client approval, contract conditions, reported risk level, source refs and optional settlement ID. Risk confirms the milestone exists in that correlated Planner output before considering ALLOW.
5. An ALLOW may move the local settlement record to `AUTHORIZED`; only an owner-supplied `SETTLEMENT_UPDATED` can report submission. The monitor observes pending/final status through its separate read-only adapter.

Each payload is validated at ingestion. Planner, Evidence, Risk and Settlement executions, outputs, reasons, source refs, versions and input hashes are available through `/api/agents/{planner|evidence|risk|settlement}/history`. Event history exposes the shared correlation ID.

## Agent rules

### Planner `planner/1.1-local`

The proposed default plan has Analysis 10%, Backend 30%, Frontend 30%, Tests & validation 15%, and Deployment 15%. A largest-remainder allocator distributes both work units and hours as integers, preserving the exact project totals. When both dates are supplied, milestone target dates advance in proportion to cumulative allocated work units and the final date equals the requested deadline. Missing dates remain `null`. The output is explicitly `PROPOSED_REQUIRES_HUMAN_APPROVAL`; it does not write to a master project or claim actual progress.

### Evidence `evidence/1.1`

Four independently recorded checks are worth 25 points each: every referenced commit must be authored/committed by the contributor and belong to one of the referenced PRs; every referenced PR must be authored by that contributor and merged; every referenced PR must have an independent approval with no outstanding changes request; and all fetched CI checks must succeed. A hard mismatch, unmerged PR, latest independent `CHANGES_REQUESTED`, or failed CI yields `REJECTED`. All four checks must be present and pass for `VERIFIED`; incomplete data stays `UNKNOWN`. The local score is a Dev 4 test score, never Dev 2's official score. The proof hash is SHA-256 over the canonical fetched evidence and rule version. It is not a GitHub attestation, HCS record, or on-chain proof.

GitHub mode fetches commit details, PR details and commits, reviews, and check runs (falling back to combined commit status when there are no check runs). Caller-sent synthetic facts are ignored in this mode. Only the fixed `api.github.com` host is contacted. References are limited to three commits and three PRs per event; paginated commit, review, and check-run lists are read in pages of 100, up to 10 pages per list, within a 20-second total time budget. A list that exceeds the bound or has an invalid response fails closed rather than being treated as complete; the durable worker retries then quarantines according to its existing retry policy.

### Risk & Policy `risk-policy/1.1-local`

Risk reads the stored Planner and Evidence executions by ID, checks project and correlation IDs, and ignores a caller's claimed Evidence verdict/score. It confirms that the selected milestone appears in the Planner's proposed milestones, then computes an explainable risk score with capped additive weights:

| Factor | Points |
|---|---:|
| Evidence VERIFIED / UNKNOWN / REJECTED | 0 / 25 / 60 |
| Milestone incomplete / unknown | 20 / 10 |
| Client approval denied / unknown | 30 / 10 |
| Contract condition failed / unknown | 40 / 10 |
| Reported risk MEDIUM / HIGH / UNKNOWN | 20 / 40 / 10 |

Computed risk is LOW below 20, MEDIUM from 20 to 49, HIGH at 50 or more; a reported HIGH is an unconditional HIGH override. A known failed gate, rejected Evidence, or HIGH risk produces BLOCK. Missing proof or facts and MEDIUM risk produce HUMAN_REVIEW. ALLOW requires VERIFIED evidence with all four checks, score 100, every policy boolean explicitly true, and computed LOW risk. The output stores all components, reason codes, rule version, evidence event ID and source refs. A block or review creates an in-app alert.

`client_approved`, `conditions_met`, and `risk_level` are still assertions supplied by the event producer in this autonomous mini-project. Production use requires trusted/authenticated approval provenance and later alignment with Dev 3's approved policy contract. `ALLOW` here is scoped to a local simulation and cannot authorize a real transfer.

### Settlement monitor `settlement-monitor/1.1-local`

The existing state machine checks allowed transitions and requires transaction ID, explicit source finality, and consensus timestamp to confirm. This implementation performs no signing or submission. Without a live settlement adapter the status remains unconfirmed. The end-to-end tests replace that port with deterministic test adapters; their transaction IDs and observations are labeled TEST_ONLY.

## GitHub setup

In the process environment, configure the following values (`backend/.env.example` is a reference file; Django does not load `.env` automatically):

```dotenv
FW_MODE_EVIDENCE=github
FW_GITHUB_TOKEN=YOUR_FINE_GRAINED_READ_ONLY_TOKEN
FW_GITHUB_ALLOWED_REPOSITORIES=owner/repository
```

Grant only the repository read permissions needed for Contents, Pull requests, Checks and Commit statuses. Keep the token out of source control, event payloads and logs. `FW_GITHUB_ALLOWED_REPOSITORIES` is mandatory in GitHub mode. In `FW_MODE_EVIDENCE=local`, the fixture fields are used and every result is marked `LOCAL_TEST_ONLY`/`synthetic_data: true`.

The request must include `repository`, `contributor_login`, `commit_shas`, and `pull_request_numbers`; the SHA and PR references are claims used only to select objects for server-side retrieval. A `VERIFIED` result means those fetched objects pass the local rule. It does not prove that the selected work belongs to a particular milestone unless the producer's work-to-commit mapping is separately trusted.

## Verification

From `backend/`:

```powershell
python manage.py test command_center.test_phase5 --verbosity 2
python manage.py test command_center --verbosity 2
python manage.py check
python manage.py makemigrations --check --dry-run
```

The focused tests cover a synthetic ALLOW path from engagement planning through Evidence, Risk, settlement submission, pending observation and finality; a CI-failure BLOCK path; missing-evidence HUMAN_REVIEW; a mocked GitHub API verification where caller-supplied false claims are ignored; and the existing settlement failure/transition guards. No test requires a GitHub token or network access.
