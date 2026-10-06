# FUTUREWORK: Dev 2, Evidence & Consensus

Standalone Django module (port 8002, schema `fw_evidence`). Runs fully in `FW_MODE=mock`: no Dev 1/3/4, no Hedera account needed.

## Run (no Docker)
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env            # optional, defaults work for mock mode
python manage.py migrate
python manage.py replay_fixtures   # connects FW-DEMO-001 + replays push / PR / review through the pipeline
python manage.py runserver 8002
curl localhost:8002/api/evidence/milestones/M-DEMO-001/contract
pytest                              # 16 tests
```
Docker + Postgres: `docker compose -f docker-compose.mp2.yml up` (creates schema `fw_evidence`).

## Layout
| Path | Role |
|---|---|
| `backend/domain/` | Pure Python: canonical JSON + Proof Hash, `[M-###]` parser, scoring, webhook normalizers |
| `backend/ports/` | `ProjectPort GitHubPort HcsPort MirrorPort EventPort LLMPort`: `mock.py` / `real.py`, switched by `FW_MODE` or `FW_MODE_<NAME>` |
| `backend/agent/` | LangGraph agent `score_rules -> llm_review -> decide` (deterministic fallback) |
| `backend/githubint/` | repo connect, webhook (HMAC + idempotent), commit/PR/review records |
| `backend/evidence/` | Evidence, verification, hash, outbox events, pipeline (`services.process`), Evidence Contract |
| `backend/hcs/` | topic per project, idempotent submit, retry/queue, Mirror readback, sync |
| `hcs_bridge/` | tiny Node scripts (`@hashgraph/sdk`) used by the live `RealHcs` adapter |
| `contracts/fixtures/github/` | hand-written webhook payloads (replace with recorded ones) |

## Real Hedera (testnet) in 5 steps
1. **Account**: free at https://portal.hedera.com, copy Account ID + private key.
2. **Config**: `cp backend/.env.example backend/.env`, fill `HEDERA_OPERATOR_ID`, `HEDERA_OPERATOR_KEY`, and set `HEDERA_KEY_TYPE`
   (`ecdsa` for the portal's "HEX Encoded" key, `der` for keys starting `302e…`). `FW_MODE_HCS/MIRROR/GITHUB=live` are already set.
3. **Bridge**: `cd hcs_bridge && npm install` (Node 18+).
4. **Preflight**: `cd backend && python manage.py hedera_check`. It checks your balance, creates a topic, submits a message,
   reads it back from the Mirror Node and prints HashScan links. **Run this first; if it passes, the whole module is live.**
5. **GitHub**: put a PAT in `GITHUB_TOKEN` (`repo` + `admin:repo_hook`), then
   - `POST /api/evidence/github/connect {projectId, repoFullName, workerGithub, callbackUrl}` (callbackUrl = your smee/ngrok URL + `/api/evidence/github/webhook`, creates the webhook), and/or
   - `POST /api/evidence/github/sync {projectId}` to backfill existing commits / merged PRs / reviews through the same pipeline.

Then every verified evidence produces: a Proof Hash, an HCS message on your project topic (`https://hashscan.io/testnet/topic/<id>`),
a Mirror Node readback with the consensus timestamp, and a `HCS_EVENT_SUBMITTED` event. Dev 1 / Dev 4 stay mocked
(`FW_MODE_PROJECT`, `FW_MODE_EVENTS`) until integration at J11-J12.

## Endpoints
`POST /api/evidence/github/connect | webhook` · `GET /api/evidence/github/commits|pulls|reviews` ·
`GET|POST /api/evidence` · `GET /api/evidence/:id` · `POST /api/evidence/:id/verify | attach` ·
`POST /api/evidence/github/sync` · `GET /api/evidence/overview` · `GET /api/evidence/milestones/:milestoneId/contract` ·
`POST /api/hcs/topics` · `GET|POST /api/hcs/events` · `GET /api/hcs/timeline` · `POST /api/hcs/sync` · `GET /health`
