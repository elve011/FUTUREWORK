# Phase 11 — Hedera Mirror Node observer

## What is implemented

- A `HederaObserver` port and read-only Mirror Node REST adapter for testnet and mainnet.
- Per-project explicit account, topic, token, and contract ID references. A project with no configured IDs receives no network observations.
- Transaction status/result, consensus timestamp, entity metadata, network, and HashScan links are normalized from Mirror Node responses. A missing consensus timestamp remains `null`; the observer does not turn missing or unknown information into confirmation.
- Bounded cursor pagination, HTTPS/same-host continuation validation, a request timeout, one retry for transient transport/5xx/rate-limit failures, response size limits, and a short configurable cache. When the page cap is reached with more data available, the adapter reports the feed unavailable instead of silently presenting a partial list as complete.
- API calls return HTTP 503 with `source_status=UNAVAILABLE` on live source failure. Dashboard `source_status.hedera` reports `UNAVAILABLE`.
- No account keys, signing, transaction submission, or payment behavior is included. Settlement stays separate and read-only.

## Setup: testnet first

1. Create/sign in to a Hedera Developer Portal account at [portal.hedera.com](https://portal.hedera.com/). This portal login is for obtaining a test environment/account; it is not needed by this observer at runtime.
2. Create or use a Hedera **testnet** account through the Developer Portal and record its public entity ID (`0.0.x`). Do not put its private key in this application. A read-only observer needs only public entity IDs.
3. Create/use a testnet topic, token, or smart contract only if those objects are part of the project. Record their public entity IDs and get the project owner's approval before associating them.
4. Set the environment values in the backend process (the project does not load `.env` automatically):

   ```text
   FW_MODE_HEDERA=live
   FW_HEDERA_NETWORK=testnet
   FW_HEDERA_PROJECT_REFERENCES={"FW-PROJECT-001":{"account_ids":["0.0.123"],"topic_ids":["0.0.456"],"token_ids":["0.0.789"],"contract_ids":["0.0.987"]}}
   FW_HEDERA_TIMEOUT_SECONDS=5
   FW_HEDERA_MAX_PAGES=3
   FW_HEDERA_CACHE_SECONDS=15
   ```

   Replace all example IDs with real, approved IDs; use `[]` for unused reference categories and set the JSON map key to the exact local `ProjectReference.external_id`. `FW_HEDERA_MIRROR_NODE_URL` is optional; leave it blank to use the built-in public endpoint for the selected network. An override must be an HTTPS base URL ending in `/api/v1` and must not identify the opposite network.
5. Restart the backend and request `GET /api/projects/FW-PROJECT-001/hedera/transactions`, `/hedera/activity`, and the project dashboard. Verify returned IDs/network/timestamps against the official [Hedera Mirror Node REST API](https://docs.hedera.com/hedera/sdks-and-apis/rest-api) and [HashScan testnet](https://hashscan.io/testnet). An empty list can mean that the configured account/topic has no matching public history.
6. Run the backend test suite before connecting real project references: `python backend\manage.py test command_center`.

## Before mainnet

Set `FW_HEDERA_NETWORK=mainnet` only after the project owner and other responsible developers have approved the exact public references and data association. Re-check every ID on mainnet; testnet entity IDs do not refer to the same mainnet objects. Consider using an organization-operated Mirror Node endpoint via `FW_HEDERA_MIRROR_NODE_URL` if public service availability/rate limits are insufficient.

Reading public Mirror Node data does not require a funded account or signing key. Creating/submitting transactions, executing settlements, or controlling funds is explicitly outside this phase and needs separately agreed contracts, authorization, signer custody, and security review.

## Full account-to-observation scenario

Run the deterministic end-to-end scenario from the repository root:

```powershell
& '.\.venv\Scripts\python.exe' backend\manage.py test command_center.test_phase11_full_scenario -v 2
```

It creates freelancer and client accounts through the CSRF-protected signup API, creates projects with approved and blocked repositories, processes the planner/evidence/risk outbox, records work-unit progress, rejects a CI-failing proof, blocks an unapproved milestone, reads GitHub and Mirror Node responses through mocked HTTP **GET** requests, and checks the project activity/detail/dashboard, alerts, agent actions, transaction feed, and outage behavior. It verifies that a GitHub result cannot be `VERIFIED` while the profile identity is not OAuth-verified, that an independently observed CI failure is still `REJECTED`, and that a Mirror Node outage does not create a confirmed settlement.

These fixtures do not access a real GitHub repository, user account, or Hedera project. The dashboard combines separate project feeds: activity/events and agent actions, project detail/decisions, alerts, Mirror Node activity, and the transaction feed. The Dashboard now includes recent policy decisions alongside its event/agent timeline. A live network check still requires project-authorized repository references and real testnet entity IDs.
