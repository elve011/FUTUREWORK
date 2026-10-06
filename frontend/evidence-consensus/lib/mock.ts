// Demo data = what `manage.py replay_fixtures` produces on the backend (FW-DEMO-001 / M-DEMO-001).
import type { EvidenceDetail, HcsEvent, Reason, Snapshot } from "./api";

const CODES = ["MILESTONE_LINKED", "AUTHOR", "SIZE", "TESTS", "MESSAGE", "REVIEW", "CI"];
const MAX = [25, 15, 15, 15, 10, 10, 10];
const rs = (pts: number[], det: string[]): Reason[] =>
  [...pts.map((p, i) => ({ code: CODES[i], points: p, max: MAX[i], detail: det[i] })),
   { code: "LLM_REVIEW", points: 0, max: 10, detail: "consistent: no anomaly" }];

const H1 = "sha256:9f2c41ab77d0e5c3b8a1f6d2094e7c5a3b1d8f60e2a47c95d1b3e8f0a6c2d471";
const H3 = "sha256:a548f03551058a52c50130bf16ad9839a7ec424e27f3d0796370402c59cf1cba";
const H4 = "sha256:3d7be1c09a52f84e6b1370d9c4a8e25f1b60c7d93a4e82f5b1c0d6a97e348f2b";

const base = { projectId: "FW-DEMO-001", milestoneId: "M-DEMO-001", attached: true };
const ver = (score: number, verdict: string, r: Reason[], at: string) =>
  [{ score, verdict, method: "rules+llm", reasons: r, createdAt: at }];

export const MOCK_EVIDENCE: EvidenceDetail[] = [
  { ...base, evidenceId: "EV-004", milestoneSource: "label", source: "REVIEW", sourceRef: "demo-org/demo-repo#7/review/555",
    author: "demo-client", title: "Review (approved) on PR #7", status: "ANCHORED", occurredAt: "2026-10-12T13:30:00Z",
    complianceScore: 73, proofHash: H4, metadata: {},
    verifications: ver(73, "VERIFIED", rs([25, 8, 8, 7, 10, 10, 5], ["Linked via label", "Author not checked / unknown", "Change size unknown", "Tests unknown", "Descriptive message", "Reviewed / merged", "CI status: unknown"]), "2026-10-12T13:30:05Z") },
  { ...base, evidenceId: "EV-003", milestoneSource: "label", source: "PULL_REQUEST", sourceRef: "demo-org/demo-repo#7",
    author: "demo-worker", title: "[M-DEMO-001] Evidence API and HCS anchoring", status: "ANCHORED", occurredAt: "2026-10-12T14:00:00Z",
    complianceScore: 87, proofHash: H3, metadata: {},
    verifications: ver(87, "VERIFIED", rs([25, 15, 15, 7, 10, 10, 5], ["Linked via label", "Author matches the assigned worker", "Reasonable change size (234 lines)", "Tests unknown", "Descriptive message", "Reviewed / merged", "CI status: unknown"]), "2026-10-12T14:00:04Z") },
  { ...base, evidenceId: "EV-002", milestoneSource: "branch", source: "COMMIT", sourceRef: "b2c3d4e5f60718293a4b5c6d7e8f901234567890",
    author: "demo-worker", title: "wip", status: "REJECTED", occurredAt: "2026-10-12T10:30:00Z",
    complianceScore: 53, proofHash: null, metadata: {},
    verifications: ver(53, "REJECTED", rs([25, 15, 8, 0, 0, 0, 5], ["Linked via branch", "Author matches the assigned worker", "Change size unknown", "No test changes", "Missing or generic message", "Not reviewed or merged", "CI status: unknown"]), "2026-10-12T10:30:03Z") },
  { ...base, evidenceId: "EV-001", milestoneSource: "branch", source: "COMMIT", sourceRef: "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
    author: "demo-worker", title: "feat(evidence): add webhook signature verification [M-DEMO-001]", status: "ANCHORED",
    occurredAt: "2026-10-12T10:00:00Z", complianceScore: 78, proofHash: H1, metadata: {},
    verifications: ver(78, "VERIFIED", rs([25, 15, 8, 15, 10, 0, 5], ["Linked via branch", "Author matches the assigned worker", "Change size unknown", "Tests touched", "Descriptive message", "Not reviewed or merged", "CI status: unknown"]), "2026-10-12T10:00:04Z") },
];

const ev = (id: string, ev_id: string, seq: number, h: string, status: string, ts: string | null): HcsEvent => ({
  id, eventType: "EVIDENCE_VERIFIED", evidenceId: ev_id, milestoneId: "M-DEMO-001", projectId: "FW-DEMO-001",
  proofHash: h, status, topicId: "0.0.1002", sequenceNumber: seq, consensusTimestamp: ts,
  transactionId: `0.0.1234@${1760000000 + seq}.000000000`, readbackOk: ts ? true : null, attempts: 1, lastError: null,
  hashscanUrl: "https://hashscan.io/testnet/topic/0.0.1002",
});

export const MOCK: Omit<Snapshot, "source"> = {
  overview: { total: 4, byStatus: { ANCHORED: 3, REJECTED: 1 }, unattached: 0, averageScore: 72.8 },
  evidence: MOCK_EVIDENCE,
  commits: [
    { sha: "b2c3d4e5f607", message: "wip", author: "demo-worker", branch: "feat/M-DEMO-001-evidence-api", committedAt: "2026-10-12T10:30:00Z", filesChanged: 1, milestoneId: "M-DEMO-001", repo: "demo-org/demo-repo" },
    { sha: "a1b2c3d4e5f6", message: "feat(evidence): add webhook signature verification [M-DEMO-001]", author: "demo-worker", branch: "feat/M-DEMO-001-evidence-api", committedAt: "2026-10-12T10:00:00Z", filesChanged: 2, milestoneId: "M-DEMO-001", repo: "demo-org/demo-repo" },
  ],
  pulls: [{ number: 7, title: "[M-DEMO-001] Evidence API and HCS anchoring", author: "demo-worker", branch: "feat/M-DEMO-001-evidence-api", merged: true, additions: 220, deletions: 14, labels: ["milestone:M-DEMO-001"], milestoneId: "M-DEMO-001", repo: "demo-org/demo-repo" }],
  reviews: [{ reviewId: 555, prNumber: 7, reviewer: "demo-client", state: "approved", submittedAt: "2026-10-12T13:30:00Z", milestoneId: "M-DEMO-001", repo: "demo-org/demo-repo" }],
  events: [
    ev("1", "EV-001", 1, H1, "CONFIRMED", "1760000001.000000001"),
    ev("2", "EV-003", 2, H3, "CONFIRMED", "1760000002.000000001"),
    ev("3", "EV-004", 3, H4, "SUBMITTED", null), // shows the "pending Mirror readback" state
  ],
};
