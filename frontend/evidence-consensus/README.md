# FUTUREWORK: Evidence & Consensus dashboard (Dev 2)

Next.js 14 + TypeScript + Tailwind, port 3002.

```bash
npm install
cp .env.example .env.local
npm run dev        # http://localhost:3002
```
- Backend on `NEXT_PUBLIC_API_URL` (default `http://localhost:8002`). If it is down, the page shows **demo data** (badge "Demo data").
- `NEXT_PUBLIC_FW_MODE=mock` forces demo data, `live` disables the fallback.
- Drop into the monorepo as `frontend/evidence-consensus/`.

Sections map to the spec: Evidence Overview, pipeline, evidence list + AI verification (explainable score), GitHub Activity
(commits / PRs / reviews), Consensus Timeline, HCS Events (Topic ID, sequence, consensus timestamp, HashScan link).
Actions: **Sync HCS** (`POST /api/hcs/sync`) and **Run verification** (`POST /api/evidence/:id/verify`).
