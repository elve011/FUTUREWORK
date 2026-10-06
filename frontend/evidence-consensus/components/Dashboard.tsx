"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity, ArrowRight, Bell, Bot, Boxes, ExternalLink, FileText, GitBranch, GitCommit, GitPullRequest, Hash,
  LayoutDashboard, MessageSquare, RefreshCw, Settings, ShieldCheck, Wallet, type LucideIcon,
} from "lucide-react";
import { loadDetail, loadSnapshot, post, verifyOnMirror, type EvidenceDetail, type HcsEvent, type Snapshot } from "@/lib/api";
import { Card, DOTS, Pill, ScoreRing, StatusPill, fmtConsensus, fmtIso, shortHash, toneOf } from "./ui";

const NAV: [string, string, LucideIcon][] = [
  ["Dashboard", "#top", LayoutDashboard], ["Evidence", "#evidence", ShieldCheck], ["GitHub Activity", "#github", GitBranch],
  ["HCS Events", "#hcs", Hash], ["Consensus Timeline", "#timeline", Activity],
];
const SRC_ICON: Record<string, LucideIcon> = { COMMIT: GitCommit, PULL_REQUEST: GitPullRequest, REVIEW: MessageSquare, MANUAL: FileText };

type StepState = "done" | "active" | "pending";
const STEP_STYLE: Record<StepState, [string, string, string]> = {
  done: ["border-ok/40 bg-ok/10 text-ok", "text-ok", "Completed"],
  active: ["border-brand/50 bg-brand/15 text-brand", "text-brand", "In Progress"],
  pending: ["border-line bg-panel2 text-muted", "text-muted", "Pending"],
};

function pipeline(s: Snapshot): { label: string; icon: LucideIcon; state: StepState }[] {
  const ev = s.evidence, hs = s.events;
  const waiting = ev.some((e) => e.attached && ["COLLECTED", "VERIFYING"].includes(e.status));
  const judged = ev.some((e) => ["VERIFIED", "ANCHORED", "REJECTED"].includes(e.status));
  const hashed = ev.some((e) => e.proofHash);
  const unanchored = ev.some((e) => e.status === "VERIFIED");
  const sent = hs.some((h) => h.sequenceNumber != null);
  const pick = (done: boolean, active: boolean): StepState => (active ? "active" : done ? "done" : "pending");
  return [
    { label: "GitHub Evidence", icon: GitBranch, state: pick(ev.length > 0, false) },
    { label: "AI Verification", icon: Bot, state: pick(judged, waiting) },
    { label: "Proof Hash", icon: Hash, state: pick(hashed, unanchored) },
    { label: "HCS Submit", icon: Boxes, state: pick(sent, hs.some((h) => h.status === "QUEUED")) },
    { label: "Mirror Confirm", icon: ShieldCheck, state: pick(hs.length > 0 && hs.every((h) => h.status === "CONFIRMED"), hs.some((h) => h.status === "SUBMITTED")) },
  ];
}

function Stat({ icon: Icon, label, value, sub, tone }: { icon: LucideIcon; label: string; value: string | number; sub?: string; tone: string }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-line bg-panel/90 p-4">
      <div className={`grid h-11 w-11 place-items-center rounded-xl ${tone}`}><Icon size={20} /></div>
      <div>
        <div className="text-xs text-muted">{label}</div>
        <div className="text-2xl font-semibold leading-tight text-white">{value}</div>
        {sub && <div className="text-[11px] text-muted">{sub}</div>}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [projectId, setProjectId] = useState("FW-DEMO-001");
  const [draft, setDraft] = useState("FW-DEMO-001");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<EvidenceDetail | null>(null);
  const [tab, setTab] = useState<"commits" | "pulls" | "reviews">("commits");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [chain, setChain] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    try {
      setSnap(await loadSnapshot(projectId));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [projectId]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (snap && !selected && snap.evidence[0]) setSelected(snap.evidence[0].evidenceId);
  }, [snap, selected]);

  useEffect(() => {
    if (!snap || !selected) return;
    loadDetail(selected, snap.source).then(setDetail).catch(() => setDetail(null));
  }, [snap, selected]);

  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 3500); };
  const act = async (fn: () => Promise<string>) => {
    if (snap?.source === "mock") return flash("Demo data: start the Django API on :8002 to run live actions.");
    setBusy(true);
    try { flash(await fn()); await refresh(); } catch (e) { flash(`Failed: ${(e as Error).message}`); } finally { setBusy(false); }
  };
  const sync = () => act(async () => {
    const r = await post<{ resubmitted: number; readbackChecked: number }>("/api/hcs/sync");
    return `HCS sync: ${r.resubmitted} resubmitted, ${r.readbackChecked} readbacks checked`;
  });
  const syncGithub = () => act(async () => {
    const r = await post<{ processed: number; evidence: string[] }>("/api/evidence/github/sync", { projectId });
    return `GitHub sync: ${r.processed} new deliveries, ${r.evidence.length} evidence collected`;
  });
  const checkChain = async (e: HcsEvent) => {
    const key = String(e.id);
    if (e.sequenceNumber == null) return;
    setChain((c) => ({ ...c, [key]: "checking" }));
    try {
      const r = await verifyOnMirror(e.topicId, e.sequenceNumber, e.proofHash);
      setChain((c) => ({ ...c, [key]: r.state }));
    } catch { setChain((c) => ({ ...c, [key]: "error" })); }
  };
  const verify = () => act(async () => { await post(`/api/evidence/${selected}/verify`); return `${selected} processed`; });

  const ov = snap?.overview;
  const latest = detail?.verifications.at(-1);
  const sortedEvents = snap ? [...snap.events].sort((a, b) => (a.sequenceNumber ?? 1e9) - (b.sequenceNumber ?? 1e9)) : [];
  const canVerify = !!detail && detail.attached && ["COLLECTED", "VERIFIED"].includes(detail.status);

  return (
    <div id="top" className="flex min-h-screen">
      {/* ---------- Sidebar ---------- */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-sidebar p-4 lg:flex">
        <div className="mb-6 flex items-center gap-2.5 px-2">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-brand to-violet text-sm font-bold text-white">F</div>
          <span className="text-sm font-bold tracking-wider text-white">FUTUREWORK</span>
        </div>
        <nav className="flex flex-col gap-1">
          {NAV.map(([label, href, Icon], i) => (
            <a key={label} href={href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${i === 1 ? "bg-brand/15 text-white ring-1 ring-brand/30" : "text-muted hover:bg-white/5 hover:text-white"}`}>
              <Icon size={16} />{label}
            </a>
          ))}
          <div className="my-2 border-t border-line" />
          {([["Wallet", Wallet], ["Settings", Settings]] as [string, LucideIcon][]).map(([l, Icon]) => (
            <span key={l} className="flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted/50"><Icon size={16} />{l}</span>
          ))}
        </nav>
        <div className="mt-auto flex items-center gap-3 rounded-xl border border-line bg-panel p-3">
          <div className="grid h-9 w-9 place-items-center rounded-full bg-gradient-to-br from-cyan to-brand text-xs font-bold text-bg">D2</div>
          <div className="text-xs"><div className="font-medium text-white">Evidence & Consensus</div><div className="text-muted">Module 2 · port 3002</div></div>
        </div>
      </aside>

      {/* ---------- Main ---------- */}
      <main className="min-w-0 flex-1 space-y-5 p-5 lg:p-7">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-white">Evidence & Consensus</h1>
            <p className="text-sm text-muted">From work to proof, from proof to consensus, anchored on Hedera HCS.</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <input value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={() => setProjectId(draft.trim() || projectId)}
              onKeyDown={(e) => e.key === "Enter" && setProjectId(draft.trim() || projectId)}
              className="w-36 rounded-lg border border-line bg-panel px-3 py-2 text-sm text-white outline-none focus:border-brand" aria-label="Project ID" />
            <Pill tone={snap?.source === "live" ? "ok" : "warn"}>{snap?.source === "live" ? "● Live · Hedera Testnet" : "● Demo data (mock mode)"}</Pill>
            <button onClick={syncGithub} disabled={busy}
              className="flex items-center gap-2 rounded-lg border border-line bg-panel px-4 py-2 text-sm text-white transition hover:border-brand disabled:opacity-50">
              <GitBranch size={14} />Sync GitHub
            </button>
            <button onClick={sync} disabled={busy}
              className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-brand to-violet px-4 py-2 text-sm font-medium text-white shadow-lg shadow-brand/20 transition hover:opacity-90 disabled:opacity-50">
              <RefreshCw size={14} className={busy ? "animate-spin" : ""} />Sync HCS
            </button>
            <Bell size={18} className="text-muted" />
          </div>
        </header>

        {error && <div className="rounded-xl border border-bad/30 bg-bad/10 px-4 py-3 text-sm text-bad">API error: {error}</div>}
        {!snap && !error && <div className="text-sm text-muted">Loading…</div>}

        {snap && ov && (<>
          {/* Evidence Overview */}
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat icon={ShieldCheck} label="Total Evidence" value={ov.total} sub={`${ov.unattached} unattached`} tone="bg-brand/15 text-brand" />
            <Stat icon={Boxes} label="Anchored on HCS" value={ov.byStatus.ANCHORED ?? 0} sub={`${snap.events.length} HCS events`} tone="bg-ok/15 text-ok" />
            <Stat icon={Activity} label="Rejected" value={ov.byStatus.REJECTED ?? 0} sub="below threshold or blocked" tone="bg-warn/15 text-warn" />
            <Stat icon={Bot} label="Avg Compliance" value={ov.averageScore ?? "–"} sub="out of 100" tone="bg-violet/15 text-violet" />
          </div>

          {/* Pipeline */}
          <Card title="Evidence Pipeline">
            <div className="flex flex-wrap items-center justify-between gap-y-4">
              {pipeline(snap).map((s, i, arr) => {
                const [ring, text, label] = STEP_STYLE[s.state];
                return (
                  <div key={s.label} className="flex flex-1 items-center">
                    <div className="flex min-w-[110px] flex-col items-center gap-2 text-center">
                      <div className={`grid h-12 w-12 place-items-center rounded-full border ${ring}`}><s.icon size={20} /></div>
                      <div className="text-xs font-medium text-white">{s.label}</div>
                      <div className={`text-[11px] ${text}`}>{label}</div>
                    </div>
                    {i < arr.length - 1 && <ArrowRight size={14} className="mx-1 hidden flex-1 text-line sm:block" />}
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Evidence table + verification detail */}
          <div className="grid gap-5 xl:grid-cols-3">
            <Card id="evidence" title="Collected Evidence" className="xl:col-span-2" right={<span className="text-xs text-muted">{snap.evidence.length} items</span>}>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[13px]">
                  <thead className="text-xs text-muted"><tr>
                    {["ID", "Source", "Author", "Milestone", "Score", "Status"].map((h) => <th key={h} className="pb-2 font-medium">{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {snap.evidence.map((e) => {
                      const Icon = SRC_ICON[e.source] ?? FileText;
                      return (
                        <tr key={e.evidenceId} onClick={() => setSelected(e.evidenceId)}
                          className={`cursor-pointer border-t border-line transition hover:bg-white/[.03] ${selected === e.evidenceId ? "bg-brand/10" : ""}`}>
                          <td className="py-3 pr-3 font-mono text-xs text-white">{e.evidenceId}</td>
                          <td className="pr-3"><div className="flex items-center gap-2"><Icon size={14} className="text-muted" /><span className="max-w-[240px] truncate">{e.title || e.sourceRef}</span></div></td>
                          <td className="pr-3 text-muted">{e.author}</td>
                          <td className="pr-3">{e.milestoneId ? <Pill tone="info">{e.milestoneId}</Pill> : <Pill tone="warn">Unattached</Pill>}</td>
                          <td className="pr-3">
                            <div className="flex items-center gap-2"><span className="w-6 text-white">{e.complianceScore ?? "–"}</span>
                              <div className="h-1.5 w-16 rounded-full bg-line"><div className={`h-full rounded-full ${(e.complianceScore ?? 0) >= 60 ? "bg-ok" : "bg-warn"}`} style={{ width: `${e.complianceScore ?? 0}%` }} /></div></div>
                          </td>
                          <td><StatusPill status={e.status} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card title="AI Verification" right={detail && <span className="font-mono text-xs text-muted">{detail.evidenceId}</span>}>
              {!detail || !latest ? <p className="text-sm text-muted">Select an evidence to see why it was accepted or rejected.</p> : (<>
                <div className="flex items-center gap-4">
                  <ScoreRing value={latest.score} />
                  <div className="space-y-1.5 text-sm">
                    <StatusPill status={detail.status} />
                    <div className="text-xs text-muted">Method: {latest.method}</div>
                    <div className="text-xs text-muted">Proof: <span className="font-mono text-slate-300">{shortHash(detail.proofHash)}</span></div>
                  </div>
                </div>
                <ul className="mt-4 space-y-2.5">
                  {latest.reasons.map((r) => (
                    <li key={r.code}>
                      <div className="flex justify-between text-[11px]"><span className="text-slate-300">{r.code.replace(/_/g, " ")}</span><span className="text-muted">{r.points}/{r.max}</span></div>
                      <div className="mt-1 h-1 rounded-full bg-line"><div className={`h-full rounded-full ${r.points === 0 ? "bg-bad" : r.points < r.max ? "bg-warn" : "bg-ok"}`} style={{ width: `${(r.points / r.max) * 100}%` }} /></div>
                      <div className="mt-0.5 text-[11px] text-muted">{r.detail}</div>
                    </li>
                  ))}
                </ul>
                {canVerify && <button onClick={verify} disabled={busy} className="mt-4 w-full rounded-lg border border-brand/40 bg-brand/10 py-2 text-sm text-brand transition hover:bg-brand/20 disabled:opacity-50">Run verification</button>}
              </>)}
            </Card>
          </div>

          {/* GitHub activity + timeline */}
          <div className="grid gap-5 xl:grid-cols-2">
            <Card id="github" title="GitHub Activity" right={<span className="text-xs text-muted">{snap.commits[0]?.repo ?? snap.pulls[0]?.repo ?? "no repo connected"}</span>}>
              <div className="mb-3 flex gap-2">
                {([["commits", "Commits", snap.commits.length], ["pulls", "Pull Requests", snap.pulls.length], ["reviews", "Reviews", snap.reviews.length]] as const).map(([k, l, n]) => (
                  <button key={k} onClick={() => setTab(k)} className={`rounded-lg px-3 py-1.5 text-xs transition ${tab === k ? "bg-brand/15 text-white ring-1 ring-brand/30" : "text-muted hover:text-white"}`}>{l} <span className="text-muted">({n})</span></button>
                ))}
              </div>
              <ul className="divide-y divide-line text-[13px]">
                {tab === "commits" && snap.commits.map((c) => (
                  <li key={c.sha} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0"><div className="truncate text-white">{c.message}</div><div className="text-xs text-muted"><span className="font-mono">{c.sha.slice(0, 7)}</span> · {c.author} · {c.filesChanged} files</div></div>
                    {c.milestoneId ? <Pill tone="info">{c.milestoneId}</Pill> : <Pill tone="warn">Unattached</Pill>}
                  </li>))}
                {tab === "pulls" && snap.pulls.map((p) => (
                  <li key={p.number} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0"><div className="truncate text-white">#{p.number} {p.title}</div><div className="text-xs text-muted">{p.author} · <span className="text-ok">+{p.additions ?? 0}</span> <span className="text-bad">-{p.deletions ?? 0}</span></div></div>
                    <Pill tone={p.merged ? "ok" : "warn"}>{p.merged ? "Merged" : "Open"}</Pill>
                  </li>))}
                {tab === "reviews" && snap.reviews.map((r) => (
                  <li key={r.reviewId} className="flex items-center justify-between gap-3 py-2.5">
                    <div><div className="text-white">{r.reviewer} on PR #{r.prNumber}</div><div className="text-xs text-muted">{fmtIso(r.submittedAt)}</div></div>
                    <Pill tone={r.state === "approved" ? "ok" : "warn"}>{r.state}</Pill>
                  </li>))}
                {((tab === "commits" && !snap.commits.length) || (tab === "pulls" && !snap.pulls.length) || (tab === "reviews" && !snap.reviews.length)) && <li className="py-6 text-center text-muted">Nothing collected yet.</li>}
              </ul>
            </Card>

            <Card id="timeline" title="Consensus Timeline">
              <ol className="relative ml-2 space-y-5 border-l border-line pl-6">
                {sortedEvents.map((e) => (
                  <li key={e.id} className="relative">
                    <span className={`absolute -left-[31px] top-1 h-3 w-3 rounded-full ring-4 ring-panel ${DOTS[toneOf(e.status)]}`} />
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm text-white">#{e.sequenceNumber ?? "–"} · {e.eventType}</div>
                      <StatusPill status={e.status} />
                    </div>
                    <div className="mt-0.5 text-xs text-muted">{e.evidenceId} · {fmtConsensus(e.consensusTimestamp)}</div>
                    <div className="font-mono text-[11px] text-muted">{shortHash(e.proofHash)}</div>
                  </li>))}
                {!sortedEvents.length && <li className="text-sm text-muted">No HCS events yet.</li>}
              </ol>
            </Card>
          </div>

          {/* HCS events table */}
          <Card id="hcs" title="HCS Events" right={<span className="text-xs text-muted">Topic {snap.events[0]?.topicId ?? "–"}</span>}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead className="text-xs text-muted"><tr>
                  {["Type", "Evidence", "Proof Hash", "Seq #", "Consensus Timestamp", "Status", "On-chain check", ""].map((h) => <th key={h} className="pb-2 font-medium">{h}</th>)}
                </tr></thead>
                <tbody>
                  {sortedEvents.map((e) => (
                    <tr key={e.id} className="border-t border-line">
                      <td className="py-3 pr-3"><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${DOTS[toneOf(e.status)]}`} />{e.eventType}</div></td>
                      <td className="pr-3 font-mono text-xs">{e.evidenceId}</td>
                      <td className="pr-3 font-mono text-xs text-muted">{shortHash(e.proofHash)}</td>
                      <td className="pr-3">{e.sequenceNumber ?? "–"}</td>
                      <td className="pr-3 text-muted">{fmtConsensus(e.consensusTimestamp)}</td>
                      <td className="pr-3"><StatusPill status={e.status} /></td>
                      <td className="pr-3">
                        {chain[String(e.id)] === "match" ? <Pill tone="ok">Hash matches</Pill>
                          : chain[String(e.id)] === "mismatch" ? <Pill tone="bad">MISMATCH</Pill>
                          : chain[String(e.id)] === "pending" ? <Pill tone="warn">Not on mirror yet</Pill>
                          : chain[String(e.id)] === "error" ? <Pill tone="bad">Mirror error</Pill>
                          : <button onClick={() => checkChain(e)} disabled={e.sequenceNumber == null} className="text-xs text-brand hover:underline disabled:text-muted disabled:no-underline">{chain[String(e.id)] === "checking" ? "Checking…" : "Verify on Mirror Node"}</button>}
                      </td>
                      <td className="whitespace-nowrap text-xs">
                        <a href={e.hashscanUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand hover:underline">Topic <ExternalLink size={11} /></a>
                        {e.transactionUrl && <a href={e.transactionUrl} target="_blank" rel="noreferrer" className="ml-3 inline-flex items-center gap-1 text-brand hover:underline">Tx <ExternalLink size={11} /></a>}
                      </td>
                    </tr>))}
                </tbody>
              </table>
            </div>
          </Card>
        </>)}
      </main>

      {toast && <div className="fixed bottom-5 right-5 rounded-xl border border-line bg-panel2 px-4 py-3 text-sm text-white shadow-xl">{toast}</div>}
    </div>
  );
}
