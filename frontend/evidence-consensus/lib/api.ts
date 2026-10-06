// Port/Adapter on the frontend: same shapes as the Django API; falls back to demo data when the API is down.
import { MOCK, MOCK_EVIDENCE } from "./mock";

export type Reason = { code: string; points: number; max: number; detail: string };
export type Verification = { score: number; verdict: string; method: string; reasons: Reason[]; createdAt: string };
export type Evidence = {
  evidenceId: string; projectId: string; milestoneId: string | null; milestoneSource?: string | null; attached: boolean;
  source: "COMMIT" | "PULL_REQUEST" | "REVIEW" | "MANUAL"; sourceRef: string; author: string; title: string;
  status: string; occurredAt: string; complianceScore: number | null; proofHash: string | null;
};
export type EvidenceDetail = Evidence & { metadata?: Record<string, unknown>; verifications: Verification[] };
export type HcsEvent = {
  id: string | number; eventType: string; evidenceId: string; milestoneId: string; projectId: string; proofHash: string;
  status: string; topicId: string; sequenceNumber: number | null; consensusTimestamp: string | null;
  transactionId: string | null; transactionUrl?: string | null; readbackOk: boolean | null; attempts: number; lastError: string | null; hashscanUrl: string;
};
export type Overview = { total: number; byStatus: Record<string, number>; unattached: number; averageScore: number | null };
export type Commit = { sha: string; message: string; author: string; branch: string; committedAt: string; filesChanged: number; milestoneId: string | null; repo: string };
export type Pull = { number: number; title: string; author: string; branch: string; merged: boolean; additions: number | null; deletions: number | null; labels: string[]; milestoneId: string | null; repo: string };
export type Review = { reviewId: number; prNumber: number; reviewer: string; state: string; submittedAt: string; milestoneId: string | null; repo: string };
export type Snapshot = { overview: Overview; evidence: Evidence[]; commits: Commit[]; pulls: Pull[]; reviews: Review[]; events: HcsEvent[]; source: "live" | "mock" };

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8002";
const MODE = process.env.NEXT_PUBLIC_FW_MODE ?? "";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export async function post<T>(path: string, payload?: unknown): Promise<T> {
  const r = await fetch(BASE + path, { method: "POST", headers: payload ? { "Content-Type": "application/json" } : undefined, body: payload ? JSON.stringify(payload) : undefined });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body?.error?.message ?? `${r.status}`);
  return body;
}

export async function loadSnapshot(projectId: string): Promise<Snapshot> {
  if (MODE !== "mock") {
    try {
      const q = `projectId=${encodeURIComponent(projectId)}`;
      const [overview, evidence, commits, pulls, reviews, events] = await Promise.all([
        get<Overview>(`/api/evidence/overview?${q}`), get<Evidence[]>(`/api/evidence?${q}`),
        get<Commit[]>(`/api/evidence/github/commits?${q}`), get<Pull[]>(`/api/evidence/github/pulls?${q}`),
        get<Review[]>(`/api/evidence/github/reviews?${q}`), get<HcsEvent[]>(`/api/hcs/events?${q}`),
      ]);
      return { overview, evidence, commits, pulls, reviews, events, source: "live" };
    } catch (e) {
      throw e; // real mode: never hide a backend/Hedera problem behind demo data
    }
  }
  return { ...MOCK, source: "mock" };
}

const MIRROR = process.env.NEXT_PUBLIC_MIRROR_URL ?? "https://testnet.mirrornode.hedera.com";

// Independent check, straight from the browser to the public Mirror Node: is the anchored hash really on Hedera?
export async function verifyOnMirror(topicId: string, seq: number, proofHash: string) {
  const r = await fetch(`${MIRROR}/api/v1/topics/${topicId}/messages/${seq}`, { cache: "no-store" });
  if (r.status === 404) return { state: "pending" as const, consensusTimestamp: null };
  if (!r.ok) throw new Error(`Mirror Node ${r.status}`);
  const d = await r.json();
  const msg = JSON.parse(atob(d.message));
  return { state: (msg.h === proofHash ? "match" : "mismatch") as "match" | "mismatch", consensusTimestamp: d.consensus_timestamp as string };
}

export async function loadDetail(id: string, source: Snapshot["source"]): Promise<EvidenceDetail | null> {
  if (source === "mock") return MOCK_EVIDENCE.find((e) => e.evidenceId === id) ?? null;
  return get<EvidenceDetail>(`/api/evidence/${id}`);
}
