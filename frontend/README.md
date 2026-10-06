# FUTUREWORK Freelancer Dashboard

The Next.js App Router frontend provides the signed-in freelancer workspace and uses the FUTUREWORK theme. Its project and feed data comes from the Django API; missing or unavailable values are shown as unknown or unavailable rather than replaced with demo fixtures.

## Run locally

Start the backend using the instructions in [`../backend/README.md`](../backend/README.md), then start the frontend:

```powershell
npm install
npm run dev
```

Open <http://localhost:3000>. The frontend rewrites `/backend-api/*` to `BACKEND_API_URL` (default `http://127.0.0.1:8000`). Authentication uses the same-origin session and CSRF endpoints.

## Workspace views

- **Dashboard** — selected project progress, registered milestones and upcoming dates, pending evidence, alerts, agent health, and settlement counts.
- **My Projects / Create Project / Project Detail** — account-scoped projects, engagement inputs and plan status, milestones, evidence, approvals, decisions, and project event history.
- **AI Control Center / GitHub Evidence / Blockchain Explorer** — project agent activity and reasons, GitHub evidence with source references, and observed Hedera transactions and identifiers.
- **Wallet & Settlements / Alerts / Audit log / Settings** — read-only settlement lifecycle and transitions, project alerts, append-only history, and account/source status.

GitHub Evidence only reads commit, pull-request, review, and CI data. Public allowlisted repositories can be queried without a token; a server-side read-only token is optional for private repositories or GitHub API rate limits. It is never sent to the browser. If the freelancer GitHub identity is not OAuth-verified, positive repository facts still do not produce a `VERIFIED` verdict.

The navigation is responsive. The project selector scopes project feeds; the refresh control re-requests the selected account's project and feeds. The `DEMO_ONLY` wallet can send a real, fixed 0.1 HBAR transfer on **Hedera testnet** for each completed, approved demo milestone. The backend signs it with a testnet ECDSA key from its process environment; the browser never receives the key. This is a real testnet transaction (not a simulation), but it is not mainnet money. All other accounts are read-only. The Blockchain Explorer remains a read-only Mirror Node view.

### Test the Hedera testnet wallet

From the repository root, run the backend migrations and create the demo scenario:

```powershell
python backend\manage.py migrate
python backend\manage.py seed_hedera_demo
```

The command prints the one-time password only when it creates the demo account. Keep it locally. The sample project links to `elve011/repo-test`; preloaded evidence and approvals are synthetic `TEST_ONLY` fixtures, not GitHub-verified work. Run the backend with `FW_MODE_EVIDENCE=github` and `FW_GITHUB_ALLOWED_REPOSITORIES=elve011/repo-test` to read public commits, PRs, reviews, and CI. The account's GitHub login is an unverified claim, not OAuth identity verification. Submit the prefilled commit/PR evidence from **Project Detail**, run `process_events --once`, and inspect the result. Then open **Wallet & Settlements** and press **Envoyer 0,1 HBAR** for an eligible milestone. The backend signs and submits the transfer to testnet; confirm the sender, recipient, and network in the browser prompt. Each milestone can be paid only once; an uncertain result stays locked until reconciled in HashScan. Never use a private key posted in a chat, or these demo credentials outside local development.

## Validation

```powershell
npm run lint
npm run build
```
