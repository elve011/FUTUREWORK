import type { ReactNode } from "react";

export function Card({ id, title, right, children, className = "" }: {
  id?: string; title?: string; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section id={id} className={`scroll-mt-24 rounded-2xl border border-line bg-panel/90 ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between px-5 pb-3 pt-4">
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          {right}
        </header>
      )}
      <div className="px-5 pb-5">{children}</div>
    </section>
  );
}

export const TONES = {
  ok: "bg-ok/10 text-ok border-ok/25", info: "bg-brand/10 text-brand border-brand/25",
  warn: "bg-warn/10 text-warn border-warn/25", bad: "bg-bad/10 text-bad border-bad/25",
  mute: "bg-white/5 text-muted border-line",
} as const;
export type Tone = keyof typeof TONES;
export const DOTS: Record<Tone, string> = { ok: "bg-ok", info: "bg-brand", warn: "bg-warn", bad: "bg-bad", mute: "bg-muted" };

export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${TONES[tone]}`}>{children}</span>;
}

const STATUS: Record<string, [Tone, string]> = {
  ANCHORED: ["ok", "Anchored"], CONFIRMED: ["ok", "Confirmed"], VERIFIED: ["ok", "Verified"],
  REJECTED: ["bad", "Rejected"], FAILED: ["bad", "Failed"], COLLECTED: ["warn", "Pending"],
  QUEUED: ["warn", "Queued"], VERIFYING: ["info", "Verifying"], SUBMITTED: ["info", "Submitted"],
};
export const toneOf = (s: string): Tone => STATUS[s]?.[0] ?? "mute";
export function StatusPill({ status }: { status: string }) {
  return <Pill tone={toneOf(status)}>{STATUS[status]?.[1] ?? status}</Pill>;
}

export function ScoreRing({ value, size = 120 }: { value: number | null; size?: number }) {
  const r = (size - 14) / 2, c = 2 * Math.PI * r, pct = value ?? 0;
  const color = pct >= 80 ? "#22C55E" : pct >= 60 ? "#22D3EE" : "#F59E0B";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#16233F" strokeWidth="8" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={`${(c * pct) / 100} ${c}`} />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <div className="text-center leading-none">
          <div className="text-2xl font-semibold text-white">{value ?? "–"}</div>
          <div className="mt-1 text-[10px] text-muted">/ 100</div>
        </div>
      </div>
    </div>
  );
}

export function shortHash(h?: string | null, n = 8) {
  if (!h) return "—";
  const raw = h.replace("sha256:", "");
  return raw.length <= n * 2 ? raw : `${raw.slice(0, n)}…${raw.slice(-4)}`;
}

export const fmtIso = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

// Hedera consensus timestamp "seconds.nanos" -> readable
export const fmtConsensus = (ts?: string | null) =>
  ts ? new Date(Number(ts.split(".")[0]) * 1000).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "pending readback";
