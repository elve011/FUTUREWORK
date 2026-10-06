"use client";

import {
  Activity, AlertTriangle, ArrowRight,
  Bell, Blocks, Bot, BriefcaseBusiness, Check, ChevronDown, CircleHelp,
  Clock3, Coins, Command, ExternalLink, FileCheck2, Fingerprint,
  LayoutDashboard, ListChecks, Menu, RefreshCw, Search, Settings2, ShieldCheck, Wallet, X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AuthUser, postAuth, postWithCsrf } from "../lib/auth";
import WalletPayment from "./wallet-payment";

type Agent = { id: string; name: string; status: string; health_status: string; agent_version: string; capabilities: string[]; last_activity_at: string | null; last_heartbeat_at: string | null };
type ProjectReference = { project_id: string; title: string; status: string; description: string; provenance: string; created_at: string; updated_at: string };
type ProjectWorkspace = {
  agreement: { total_hours: number | null; total_work_units: number | null; start_date: string | null; target_deadline: string | null; github_repository: string; conditions: string[]; approval_status: string; plan_status: string; provenance: string } | null;
  milestones: { milestone_id: string; title: string; planned_work_units: number | null; estimated_hours: number | null; completed_work_units: number | null; target_date: string | null; status: string; provenance: string }[];
  evidence: { evidence_id: string; milestone_id: string | null; source: string; status: string; repository?: string | null; score: number | null; proof_hash: string | null; reasons: string[]; source_refs: unknown[]; source_event_id: string }[];
  approvals: { kind: string; milestone_id?: string | null; decision: string; reason: string; actor_id: string; created_at: string }[];
  events: { event_id: string; event_type: string; status: string; correlation_id: string | null; occurred_at: string }[];
  decisions: { decision: string; reason_code: string; reason: string; event_id: string; policy_version: string }[];
};
type ActivityItem = { kind?: string; agent_id?: string; actor_id?: string; event_id: string; event_type?: string; trace_id: string; status: string; processing_status?: string; summary?: string; at: string };
type AlertItem = { id?: number; type: string; severity: string; title: string; trace_id: string; created_at: string; resolved_at?: string | null };
type Hederaitem = {
  id: string; kind: string; summary: string; consensus_timestamp: string | null; hashscan_url: string; source: string;
  topic_id?: string; token_id?: string; contract_id?: string; scheduled_transaction_id?: string;
};
type TransactionItem = { transaction_id: string; kind: string; status: string; consensus_timestamp: string | null; hashscan_url: string };
type SettlementItem = { settlement_id: string; project_id: string; trace_id: string; status: string; transaction_id: string | null; consensus_timestamp: string | null; network: string | null; source: string | null; last_observed_at: string | null; last_checked_at: string | null; last_error_code: string | null; updated_at: string };
type ViewKey = "dashboard" | "projects" | "create" | "detail" | "agents" | "github" | "explorer" | "wallet" | "alerts" | "audit" | "settings";
type Dashboard = {
  project: {
    project_id: string; title: string; status: string; updated_at?: string; description?: string; provenance?: string; progress_percent: number | null;
    units: { completed: number | null; total: number | null }; milestones: { completed: number | null; total: number | null };
    evidence: { submitted: number | null; verified: number | null; missing: number | null };
    risk: { level: string; open_items: number | null };
    settlements: { confirmed: number | null; pending: number | null; failed: number | null };
  };
  agents: Agent[]; agent_activity: ActivityItem[]; alerts: AlertItem[];
  hedera_activity: Hederaitem[]; sources: { project: string; events: string; evidence: string; hedera: string };
  source_status: { hedera: string };
  event_queue?: Record<string, number>;
};

const emptyDashboard: Dashboard = {
  project: { project_id: "", title: "", status: "UNKNOWN", progress_percent: null, units: { completed: null, total: null }, milestones: { completed: null, total: null }, evidence: { submitted: null, verified: null, missing: null }, risk: { level: "UNKNOWN", open_items: null }, settlements: { confirmed: null, pending: null, failed: null } },
  agents: [], agent_activity: [], alerts: [], hedera_activity: [],
  sources: { project: "local-registry", events: "local-registry", evidence: "local", hedera: "not-configured" },
  source_status: { hedera: "no_observations" }, event_queue: {},
};

const navItems: Array<{ key: ViewKey; label: string; icon: typeof LayoutDashboard }> = [
  { key: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { key: "projects", label: "My Projects", icon: BriefcaseBusiness },
  { key: "create", label: "Create Project", icon: ListChecks },
  { key: "detail", label: "Project Detail", icon: FileCheck2 },
  { key: "agents", label: "AI Control Center", icon: Bot },
  { key: "github", label: "GitHub Evidence", icon: FileCheck2 },
  { key: "explorer", label: "Blockchain Explorer", icon: Blocks },
  { key: "wallet", label: "Wallet & Settlements", icon: Wallet },
  { key: "alerts", label: "Alerts", icon: Bell },
  { key: "audit", label: "Audit log", icon: Activity },
  { key: "settings", label: "Settings", icon: Settings2 },
];

function activityState(item: ActivityItem) { return item.processing_status && item.processing_status !== "LEGACY" ? item.processing_status : item.status; }
function agentStateLabel(agent: Agent) {
  if (agent.health_status === "STALE") return "Stale heartbeat";
  if (agent.health_status !== "AVAILABLE") return "Unknown health";
  if (agent.status === "RUNNING") return "Working";
  if (agent.status === "BLOCKED") return "Task blocked";
  return "Ready";
}
function activityLabel(item: ActivityItem) {
  if (item.kind === "PROJECT_AUDIT") return "recorded in project audit";
  switch (activityState(item)) {
    case "PENDING": return "queued for processing";
    case "PROCESSING": return "being processed";
    case "RETRY": return "scheduled for retry";
    case "QUARANTINED": return "quarantined for review";
    case "PROCESSED": return "processed";
    case "BLOCKED": return "blocked for review";
    case "FAILED": return "failed";
    default: return "received";
  }
}

function formatTime(value?: string | null) {
  if (!value) return "No activity yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Time unavailable";
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function showMetric(value: number | null) { return value === null ? "—" : value; }
function metricPercent(value: number | null, total: number | null) {
  if (value === null || total === null || total <= 0) return null;
  return Math.max(0, Math.min(100, value / total * 100));
}

function initials(name: string) {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function Donut({ value, label }: { value: number; label: string }) {
  return <div className="donut" style={{ "--progress": `${value}%` } as React.CSSProperties}>
    <div className="donut-center"><strong>{value}%</strong><span>{label}</span></div>
  </div>;
}

function EventTrendChart({ events }: { events: ActivityItem[] }) {
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date();
    date.setHours(0, 0, 0, 0);
    date.setDate(date.getDate() - (6 - index));
    return {
      key: `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`,
      label: new Intl.DateTimeFormat("fr-FR", { weekday: "short" }).format(date),
      count: 0,
    };
  });
  const dayIndexes = new Map(days.map((day, index) => [day.key, index]));
  events.forEach((event) => {
    const date = new Date(event.at);
    if (Number.isNaN(date.getTime())) return;
    const index = dayIndexes.get(`${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`);
    if (index !== undefined) days[index].count += 1;
  });
  const maximum = Math.max(1, ...days.map((day) => day.count));
  const points = days.map((day, index) => ({
    x: 28 + index * 104,
    y: 132 - (day.count / maximum) * 94,
  }));
  const line = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
  const area = `${line} L ${points[points.length - 1].x} 144 L ${points[0].x} 144 Z`;
  const total = days.reduce((sum, day) => sum + day.count, 0);

  return <div className="trend-chart">
    <div className="chart-summary"><strong>{total}</strong><span>événements sur 7 jours</span><span className="chart-legend"><i /> Activité observée</span></div>
    {total > 0 ? <>
      <svg className="chart-svg" viewBox="0 0 680 160" role="img" aria-label="Nombre d’événements réels observés par jour sur les sept derniers jours">
        <defs><linearGradient id="event-area-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#6577eb" stopOpacity=".2" /><stop offset="100%" stopColor="#6577eb" stopOpacity="0" /></linearGradient></defs>
        {[38, 85, 132].map((y) => <line className="chart-gridline" key={y} x1="20" x2="660" y1={y} y2={y} />)}
        <path d={area} fill="url(#event-area-fill)" />
        <path d={line} className="chart-line" />
        {points.map((point, index) => <circle className="chart-point" cx={point.x} cy={point.y} key={days[index].key} r="3.5"><title>{days[index].label} : {days[index].count} événement(s)</title></circle>)}
      </svg>
      <div className="chart-labels">{days.map((day) => <span key={day.key}>{day.label}</span>)}</div>
    </> : <div className="chart-empty">Aucun événement horodaté à afficher sur les sept derniers jours.</div>}
  </div>;
}

type ImportPreview = {
  batch_id: string; status: string; file_sha256: string; accepted_count: number; rejected_count: number;
  accepted: Array<{ external_id: string; title: string }>; rejected: Array<{ row: number; external_id?: string; errors: Record<string, string[]> }>;
  commit_url: string;
};

// Kept for the legacy operator import UI; freelancer dashboard uses the session-scoped project form below.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function ProjectWorkspacePanel({ onChanged, empty = false }: { onChanged: () => void; empty?: boolean }) {
  const [operatorId, setOperatorId] = useState("");
  const [operatorKey, setOperatorKey] = useState("");
  const [externalId, setExternalId] = useState("");
  const [title, setTitle] = useState("");
  const [projectStatus, setProjectStatus] = useState("UNKNOWN");
  const [description, setDescription] = useState("");
  const [sourceRecordId, setSourceRecordId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [previewResult, setPreviewResult] = useState<ImportPreview | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const operatorHeaders = () => ({ "X-Operator-ID": operatorId, "X-Operator-Key": operatorKey });
  const explainResponse = async (response: Response) => {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail ?? body.error ?? `API ${response.status}`);
    return body;
  };
  const createManual = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      await explainResponse(await fetch("/backend-api/projects", {
        method: "POST", headers: { ...operatorHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ external_id: externalId, title, status: projectStatus, description, source_record_id: sourceRecordId }),
      }));
      setExternalId(""); setTitle(""); setDescription(""); setSourceRecordId("");
      setMessage("Projet enregistré et audité."); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Échec de création."); }
    finally { setBusy(false); }
  };
  const previewImport = async () => {
    if (!file) { setMessage("Choisis un fichier CSV ou JSON."); return; }
    setBusy(true); setMessage(""); setPreviewResult(null);
    try {
      const form = new FormData(); form.append("file", file);
      const result = await explainResponse(await fetch("/backend-api/projects/import/preview", { method: "POST", headers: operatorHeaders(), body: form })) as ImportPreview;
      setPreviewResult(result); setMessage("Prévisualisation créée. Les lignes ne sont pas encore visibles dans le registre.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Échec de prévisualisation."); }
    finally { setBusy(false); }
  };
  const commitImport = async () => {
    if (!previewResult) return;
    setBusy(true); setMessage("");
    try {
      const commitPath = previewResult.commit_url.replace(/^\/api/, "");
      const result = await explainResponse(await fetch(`/backend-api${commitPath}`, {
        method: "POST", headers: { ...operatorHeaders(), "Content-Type": "application/json" }, body: "{}",
      }));
      setMessage(`${result.imported_count} projet(s) importé(s); les lignes refusées restent exclues.`);
      setPreviewResult(null); setFile(null); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Échec d’import."); }
    finally { setBusy(false); }
  };

  return <section className={`project-manager${empty ? " project-manager-empty" : ""}`} id="project-management">
    <div className="panel-heading"><div><div className="panel-overline">LOCAL PROJECT REGISTRY</div><h2>{empty ? "Ajouter un projet réel" : "Gérer les projets"}</h2><p>MANUAL et IMPORTED sont audités. Aucun projet de démonstration n’est préchargé ici.</p></div></div>
    <div className="operator-credentials">
      <label>Identifiant opérateur<input value={operatorId} onChange={(event) => setOperatorId(event.target.value)} autoComplete="username" placeholder="ex. emna" /></label>
      <label>Clé opérateur<input type="password" value={operatorKey} onChange={(event) => setOperatorKey(event.target.value)} autoComplete="current-password" placeholder="Clé configurée côté backend" /></label>
      <span>La clé reste en mémoire dans cette page et n’est jamais enregistrée dans le navigateur.</span>
    </div>
    <div className="project-manager-grid">
      <form className="registry-form" onSubmit={createManual}>
        <h3>Saisie manuelle</h3>
        <label>Identifiant externe<input required maxLength={128} value={externalId} onChange={(event) => setExternalId(event.target.value)} placeholder="ID fourni par votre source réelle" /></label>
        <label>Nom du projet<input required maxLength={180} value={title} onChange={(event) => setTitle(event.target.value)} /></label>
        <label>Statut fourni<input maxLength={40} value={projectStatus} onChange={(event) => setProjectStatus(event.target.value)} /></label>
        <label>Référence source<input maxLength={128} value={sourceRecordId} onChange={(event) => setSourceRecordId(event.target.value)} placeholder="Référence CRM/API, si disponible" /></label>
        <label>Description réelle<textarea maxLength={1000} value={description} onChange={(event) => setDescription(event.target.value)} rows={3} /></label>
        <button className="filter-button" disabled={busy || !operatorId || !operatorKey}>{busy ? "Enregistrement…" : "Créer et auditer"}</button>
      </form>
      <div className="registry-form">
        <h3>Import CSV ou JSON</h3>
        <p>Champs requis : <code>external_id</code>, <code>title</code>. Colonnes facultatives : status, description, source_record_id.</p>
        <label>Fichier<input type="file" accept=".csv,.json,application/json,text/csv" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreviewResult(null); }} /></label>
        <button className="filter-button" type="button" onClick={previewImport} disabled={busy || !operatorId || !operatorKey || !file}>{busy ? "Validation…" : "Valider et prévisualiser"}</button>
        {previewResult && <div className="import-preview" role="status">
          <strong>Aperçu · {previewResult.accepted_count} accepté(s), {previewResult.rejected_count} refusée(s)</strong>
          <p>SHA-256 fichier : <code>{previewResult.file_sha256}</code></p>
          {previewResult.rejected.map((row) => <p className="import-error" key={row.row}>Ligne {row.row} {row.external_id ?? ""} : {Object.values(row.errors).flat().join("; ")}</p>)}
          <button className="filter-button" type="button" onClick={commitImport} disabled={busy || previewResult.accepted_count === 0}>Confirmer l’import des lignes valides</button>
        </div>}
      </div>
    </div>
    {message && <p className="registry-message" role="status">{message}</p>}
  </section>;
}

function FreelancerProjectCreatePanel({ onChanged }: { onChanged: () => void }) {
  const [externalId, setExternalId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [totalHours, setTotalHours] = useState("100");
  const [totalUnits, setTotalUnits] = useState("100");
  const [budget, setBudget] = useState("");
  const [currency, setCurrency] = useState("HBAR");
  const [startDate, setStartDate] = useState("");
  const [deadline, setDeadline] = useState("");
  const [repository, setRepository] = useState("");
  const [conditions, setConditions] = useState("CI réussi\nApprobation client requise pour chaque milestone");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function createProject(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      await postWithCsrf("/backend-api/freelancer/projects", {
        external_id: externalId.trim(), title: title.trim(), description, status: "ACTIVE",
        total_hours: totalHours ? Number(totalHours) : null, total_work_units: totalUnits ? Number(totalUnits) : null,
        budget_amount: budget ? Number(budget) : null, currency: budget ? currency : "",
        start_date: startDate || null, target_deadline: deadline || null, github_repository: repository.trim(),
        conditions: conditions.split("\n").map((item) => item.trim()).filter(Boolean),
      });
      setExternalId(""); setTitle(""); setDescription(""); setMessage("Projet créé dans ton espace privé."); onChanged();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Création du projet impossible."); }
    finally { setBusy(false); }
  }
  return <section className="project-manager project-manager-empty" id="project-management">
    <div className="panel-heading"><div><div className="panel-overline">TON ESPACE PRIVÉ</div><h2>Créer un projet</h2><p>Le projet sera visible uniquement dans le compte qui le crée.</p></div></div>
    <form className="registry-form freelancer-project-form" onSubmit={createProject}>
      <div className="form-section">
        <div className="form-section-heading"><span>01</span><div><strong>Informations du projet</strong><small>Définissez son identité et le contexte de la mission.</small></div></div>
        <div className="form-fields two-column">
          <label>Identifiant du projet<input required maxLength={128} value={externalId} onChange={(event) => setExternalId(event.target.value)} placeholder="ex. FW-EMNA-001" /></label>
          <label>Nom du projet<input required maxLength={180} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Application web client" /></label>
          <label className="field-span">Description<textarea maxLength={1000} rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Décrivez brièvement les objectifs et le résultat attendu." /></label>
        </div>
      </div>
      <div className="form-section">
        <div className="form-section-heading"><span>02</span><div><strong>Planification & budget</strong><small>Ces objectifs structurent le suivi du travail.</small></div></div>
        <div className="form-fields two-column">
          <label>Heures prévues<input type="number" min="1" max="100000" value={totalHours} onChange={(event) => setTotalHours(event.target.value)} /></label>
          <label>Work Units<input type="number" min="1" max="100000" value={totalUnits} onChange={(event) => setTotalUnits(event.target.value)} /></label>
          <label>Budget (facultatif)<input type="number" min="0" step="0.01" value={budget} onChange={(event) => setBudget(event.target.value)} placeholder="0,00" /></label>
          <label>Devise<input maxLength={12} value={currency} onChange={(event) => setCurrency(event.target.value)} /></label>
          <label>Date de début<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
          <label>Deadline cible<input type="date" value={deadline} onChange={(event) => setDeadline(event.target.value)} /></label>
        </div>
      </div>
      <div className="form-section">
        <div className="form-section-heading"><span>03</span><div><strong>Sources & conditions</strong><small>Les sources restent côté serveur; les secrets ne doivent pas être saisis ici.</small></div></div>
        <div className="form-fields">
          <label>Dépôt GitHub facultatif (owner/repo)<input maxLength={200} value={repository} onChange={(event) => setRepository(event.target.value)} placeholder="ex. organisation/depot (sans token)" /></label>
          <label>Conditions déclarées, une par ligne<textarea rows={3} value={conditions} onChange={(event) => setConditions(event.target.value)} /></label>
        </div>
      </div>
      <div className="form-submit-row"><span>Les champs obligatoires sont indiqués par le navigateur.</span><button className="filter-button primary-form-button" disabled={busy}>{busy ? "Création…" : "Créer mon projet"} <ArrowRight size={15} /></button></div>
      {message && <p className="registry-message" role="status">{message}</p>}
    </form>
  </section>;
}

function ProjectWorkflowPanel({ projectId, user, workspace, loading, error, onChanged }: {
  projectId: string; user: AuthUser; workspace: ProjectWorkspace | null; loading: boolean; error: string; onChanged: () => void;
}) {
  const [message, setMessage] = useState("");
  const [ciStatus, setCiStatus] = useState("SUCCESS");
  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState("FREELANCER");
  const [githubCommitSha, setGithubCommitSha] = useState(projectId === "HEDERA-DEMO-001" ? "c3d98af7924dbd41c892d80597dde34d3718bddc" : "");
  const [githubPrNumber, setGithubPrNumber] = useState(projectId === "HEDERA-DEMO-001" ? "1" : "");
  async function submitTestEvidence() {
    setMessage("");
    try {
      const evidence_id = `TEST-${Date.now()}`;
      const pullRequestNumber = Date.now() % 1000000 + 1;
      await postWithCsrf(`/backend-api/freelancer/projects/${encodeURIComponent(projectId)}/evidence/test`, {
        evidence_id, milestone_id: workspace?.milestones[0]?.milestone_id,
        commits: [{ sha: "abcdef0123456789", author_id: user.email }],
        pull_requests: [{ number: pullRequestNumber, author_id: user.email, state: "MERGED", commit_shas: ["abcdef0123456789"] }],
        reviews: [{ pull_request_number: pullRequestNumber, reviewer_id: "approved-reviewer@example.test", state: "APPROVED" }],
        ci_status: ciStatus,
      });
      setMessage(`Preuve TEST_ONLY ${evidence_id} envoyée à l’outbox.`); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Envoi de la preuve impossible."); }
  }

  async function completeMilestone(item: ProjectWorkspace["milestones"][number]) {
    if (item.planned_work_units === null) return;
    try {
      await postWithCsrf(`/backend-api/freelancer/projects/${encodeURIComponent(projectId)}/milestones/${encodeURIComponent(item.milestone_id)}/complete`, { completed_work_units: item.planned_work_units });
      setMessage(`Achèvement manuel déclaré pour ${item.title}; cela ne vérifie pas sa preuve.`); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Mise à jour impossible."); }
  }

  async function approveMilestone(item: ProjectWorkspace["milestones"][number]) {
    try {
      await postWithCsrf(`/backend-api/freelancer/projects/${encodeURIComponent(projectId)}/approvals`, { kind: "MILESTONE", milestone_id: item.milestone_id, decision: "APPROVED", reason: "Approbation client explicite depuis le dashboard." });
      setMessage(`Approbation client enregistrée pour ${item.title}.`); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Approbation impossible."); }
  }

  async function evaluate(item: ProjectWorkspace["milestones"][number]) {
    const evidence = workspace?.evidence.find((row) => row.status === "VERIFIED" && row.milestone_id === item.milestone_id);
    if (!evidence) { setMessage("Il faut d’abord une preuve VERIFIED pour évaluer ce milestone."); return; }
    try {
      const result = await postWithCsrf(`/backend-api/freelancer/projects/${encodeURIComponent(projectId)}/policy-evaluations`, { milestone_id: item.milestone_id, evidence_event_id: evidence.source_event_id, conditions_met: true, risk_level: "LOW" }) as { event_id?: string };
      setMessage(`Évaluation Risk mise en file (${result.event_id}); scope LOCAL_SIMULATION_NO_TRANSFER.`); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Évaluation impossible."); }
  }

  async function addMember() {
    try {
      await postWithCsrf(`/backend-api/freelancer/projects/${encodeURIComponent(projectId)}/members`, { email: memberEmail.trim(), role: memberRole });
      setMessage(`Membre ${memberEmail} ajouté au projet.`); setMemberEmail(""); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Ajout du membre impossible."); }
  }

  async function submitGithubEvidence() {
    try {
      const response = await postWithCsrf(`/backend-api/freelancer/projects/${encodeURIComponent(projectId)}/evidence/github`, {
        evidence_id: `GH-${Date.now()}`, milestone_id: workspace?.milestones[0]?.milestone_id,
        commit_shas: [githubCommitSha.trim()], pull_request_numbers: [Number(githubPrNumber)],
      });
      setMessage(`Références GitHub mises en file: ${JSON.stringify(response)}. Le backend lit l’API avec son secret serveur.`);
      setGithubCommitSha(""); setGithubPrNumber(""); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Soumission GitHub impossible."); }
  }

  if (!workspace) return <section className="panel"><h2>Workflow Planner · Evidence · Risk</h2><p role={error ? "alert" : "status"}>{loading ? "Chargement du dossier projet…" : error || "Aucun dossier projet disponible."}</p></section>;
  return <section className="panel" id="project-workflow">
    <div className="panel-heading"><div><div className="panel-overline">PHASES 7–8 · DONNÉES PERSISTÉES</div><h2>Workflow Planner · Evidence · Risk</h2><p>Les propositions et preuves sont liées au projet, à leur source et à leur événement.</p></div></div>
    {workspace.agreement && <div className="agreement-summary">
      <div className="agreement-title"><span className="stat-icon indigo"><BriefcaseBusiness size={17} /></span><div><strong>Accord du projet</strong><small>Paramètres enregistrés et provenance conservée</small></div></div>
      <div className="agreement-facts"><div><span>Charge prévue</span><strong>{workspace.agreement.total_hours ?? "Inconnue"} h</strong></div><div><span>Work Units</span><strong>{workspace.agreement.total_work_units ?? "Inconnues"}</strong></div><div><span>État du plan</span><strong>{workspace.agreement.plan_status}</strong></div><div><span>Approbation</span><strong>{workspace.agreement.approval_status}</strong></div><div><span>Provenance</span><strong>{workspace.agreement.provenance}</strong></div></div>
    </div>}
    <div className="workflow-tools">
      {!workspace.agreement?.github_repository && <div className="workflow-tool-card"><div><strong>Soumettre une preuve de test</strong><p>Scénario local explicitement marqué comme synthétique.</p></div><div className="workflow-tool-controls"><label>Résultat CI<select value={ciStatus} onChange={(event) => setCiStatus(event.target.value)}><option value="SUCCESS">SUCCESS — scénario vérifié</option><option value="FAILURE">FAILURE — scénario rejeté</option></select></label><button className="filter-button primary-form-button" type="button" disabled={!workspace.milestones.length} onClick={submitTestEvidence}>Soumettre preuve TEST_ONLY</button></div></div>}
      {workspace.agreement?.github_repository && <div className="workflow-tool-card"><div><strong>Vérifier les références GitHub</strong><p>Les vérifications sont exécutées côté serveur; aucun token n’est demandé dans le navigateur.</p></div><div className="workflow-tool-controls"><label>Commit SHA (7–64 caractères hex)<input value={githubCommitSha} onChange={(event) => setGithubCommitSha(event.target.value)} placeholder="abcdef0123456789" /></label><label>Numéro de Pull Request<input type="number" min="1" value={githubPrNumber} onChange={(event) => setGithubPrNumber(event.target.value)} /></label><button className="filter-button primary-form-button" type="button" disabled={!workspace.milestones.length || !githubCommitSha.trim() || !githubPrNumber} onClick={submitGithubEvidence}>Vérifier via GitHub API</button></div></div>}
      <p className="member-text">{workspace.agreement?.github_repository ? `Dépôt lié : ${workspace.agreement.github_repository}. Les vérifications lisent commits, PR, reviews et CI via l’API GitHub. Le login du profil est une déclaration non OAuth : les faits publics peuvent être lus mais ne valident pas l’identité du contributeur.` : "Le fixture est explicitement synthétique. Aucun secret GitHub n’est demandé ni stocké dans le navigateur."}</p>
      {user.role !== "CLIENT" && <div className="workflow-tool-card invite-card"><div><strong>Accès au projet</strong><p>Invitez un compte déjà existant et choisissez son rôle.</p></div><div className="workflow-tool-controls"><label>Adresse e-mail<input type="email" value={memberEmail} onChange={(event) => setMemberEmail(event.target.value)} placeholder="client@example.com" /></label><label>Rôle<select value={memberRole} onChange={(event) => setMemberRole(event.target.value)}><option value="FREELANCER">FREELANCER</option><option value="CLIENT">CLIENT</option></select></label><button className="filter-button" type="button" disabled={!memberEmail.trim()} onClick={addMember}>Ajouter le membre <ArrowRight size={14} /></button></div></div>}
    </div>
    <section className="workflow-section"><div className="panel-heading"><div><div className="panel-overline">PLANNER · LIVRABLES</div><h3>Jalons du projet</h3><p>Avancement, échéance et actions autorisées pour chaque milestone.</p></div><span className="ai-badge">{workspace.milestones.length} jalons</span></div>
      {workspace.milestones.length === 0 ? <p className="empty-state">Le Planner est en attente. Laisse tourner le worker `process_events`.</p> : <div className="milestone-list">{workspace.milestones.map((item, index) => {
        const progress = item.planned_work_units && item.completed_work_units !== null ? Math.max(0, Math.min(100, item.completed_work_units / item.planned_work_units * 100)) : null;
        return <article className="milestone-card" key={item.milestone_id}>
          <div className="milestone-number">{String(index + 1).padStart(2, "0")}</div>
          <div className="milestone-main"><div className="milestone-title-row"><h4>{item.title}</h4><span className={`table-status ${item.status === "COMPLETED" ? "status-good" : "status-warning"}`}>{item.status}</span></div>
            <div className="milestone-meta"><span>ID <strong>{item.milestone_id}</strong></span><span>{item.planned_work_units ?? "Inconnues"} WU prévues</span><span>{item.completed_work_units ?? "Inconnues"} WU réalisées</span><span>{item.estimated_hours ?? "Inconnues"} h estimées</span><span>Échéance : {item.target_date ?? "Non définie"}</span><span>Source : {item.provenance}</span></div>
            <div className="milestone-progress"><div className="mini-progress">{progress !== null && <span style={{ width: `${progress}%` }} />}</div><small>{progress === null ? "Progression inconnue" : `${Math.round(progress)} % réalisé`}</small></div>
          </div>
          <div className="workflow-actions"><button type="button" className="filter-button" onClick={() => completeMilestone(item)}>Déclarer terminé</button>{user.role === "CLIENT" && <button type="button" className="filter-button" onClick={() => approveMilestone(item)}>Approuver</button>}<button type="button" className="filter-button" onClick={() => evaluate(item)}>Évaluer le risque</button></div>
        </article>;
      })}</div>}
    </section>
    <section className="workflow-section"><div className="panel-heading"><div><div className="panel-overline">EVIDENCE · PROVENANCE</div><h3>Preuves du projet</h3><p>Résultats, score, empreinte et références sources par preuve.</p></div><span className="ai-badge">{workspace.evidence.length} preuves</span></div>
      {workspace.evidence.length ? <div className="data-table-wrap"><table className="data-table evidence-table"><thead><tr><th>Identifiant</th><th>État</th><th>Milestone</th><th>Source & score</th><th>Détails</th></tr></thead><tbody>{workspace.evidence.map((item) => <tr key={item.evidence_id}><td><strong>{item.evidence_id}</strong><small className="table-secondary">{item.repository ?? "Dépôt non renseigné"}</small></td><td><span className={`table-status ${item.status === "VERIFIED" ? "status-good" : item.status === "REJECTED" ? "status-danger" : "status-warning"}`}>{item.status}</span></td><td>{item.milestone_id ?? "Sans milestone"}</td><td><strong>{item.source}</strong><small className="table-secondary">Score : {item.score === null ? "Inconnu" : `${item.score}/100`}</small></td><td><details className="table-details"><summary>Hash & références ({item.source_refs.length})</summary><div className="table-detail-content"><p><strong>Hash de preuve</strong><code>{item.proof_hash ?? "Non fourni"}</code></p><p><strong>Événement source</strong><code>{item.source_event_id}</code></p>{item.reasons.length > 0 && <ul>{item.reasons.map((reason, index) => <li key={`${item.evidence_id}-${index}`}>{reason}</li>)}</ul>}{item.source_refs.length > 0 && <pre>{JSON.stringify(item.source_refs, null, 2)}</pre>}</div></details></td></tr>)}</tbody></table></div> : <p className="empty-state">Aucune preuve enregistrée pour ce projet.</p>}
    </section>
    {workspace.approvals.length > 0 && <section className="workflow-section"><div className="panel-heading"><div><div className="panel-overline">DÉCISIONS · HUMAN APPROVAL</div><h3>Approbations explicites</h3><p>Décisions prises par les membres du projet.</p></div></div><div className="data-table-wrap"><table className="data-table"><thead><tr><th>Type</th><th>Décision</th><th>Motif</th><th>Acteur</th><th>Date</th></tr></thead><tbody>{workspace.approvals.map((item, index) => <tr key={`${item.kind}-${item.created_at}-${index}`}><td>{item.kind}<small className="table-secondary">{item.milestone_id ?? "Projet"}</small></td><td><span className="table-status status-good">{item.decision}</span></td><td>{item.reason}</td><td>{item.actor_id}</td><td>{formatTime(item.created_at)}</td></tr>)}</tbody></table></div></section>}
    <section className="workflow-section"><div className="panel-heading"><div><div className="panel-overline">RISK · POLICY</div><h3>Décisions de risque</h3><p>Résultat explicable et version de policy associée.</p></div></div>{workspace.decisions.length ? <div className="data-table-wrap"><table className="data-table decision-table"><thead><tr><th>Décision</th><th>Raison</th><th>Version policy</th><th>Événement</th></tr></thead><tbody>{workspace.decisions.map((item) => <tr key={item.event_id}><td><span className="table-status status-neutral">{item.decision}</span><small className="table-secondary">{item.reason_code}</small></td><td>{item.reason}</td><td>{item.policy_version}</td><td className="id-cell">{item.event_id}</td></tr>)}</tbody></table></div> : <p className="empty-state">Aucune décision de risque enregistrée.</p>}</section>
    <section className="workflow-section"><div className="panel-heading"><div><div className="panel-overline">APPEND-ONLY · PROJECT HISTORY</div><h3>Historique des événements</h3><p>Journal immuable des événements du projet et références corrélées.</p></div></div>{workspace.events.length ? <div className="data-table-wrap"><table className="data-table event-table"><thead><tr><th>Événement</th><th>Identifiants de traçabilité</th><th>État</th><th>Date</th></tr></thead><tbody>{workspace.events.map((item) => <tr key={item.event_id}><td><strong>{item.event_type}</strong></td><td className="id-cell">{item.event_id}{item.correlation_id && <small className="table-secondary">Corrélation : {item.correlation_id}</small>}</td><td><span className={`table-status ${item.status === "PROCESSED" ? "status-good" : "status-warning"}`}>{item.status}</span></td><td>{formatTime(item.occurred_at)}</td></tr>)}</tbody></table></div> : <p className="empty-state">Aucun événement enregistré.</p>}</section>
    {message && <p className="registry-message" role="status">{message}</p>}
  </section>;
}

function FreelancerLogoutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  async function logoutUser() {
    setBusy(true);
    try { await postAuth("logout"); } catch { /* Expired sessions are redirected to login as well. */ }
    router.replace("/login");
  }
  return <button className="auth-logout-button" type="button" onClick={logoutUser} disabled={busy}>{busy ? "Déconnexion…" : "Se déconnecter"}</button>;
}

function FreelancerDataView({ view, user, projects, projectId, dashboard, transactions, feedErrors, revision, query, onOpenProject, onRefresh }: {
  view: Exclude<ViewKey, "dashboard" | "create">; user: AuthUser; projects: ProjectReference[]; projectId: string;
  dashboard: Dashboard; transactions: TransactionItem[]; feedErrors: string[]; revision: number; query: string;
  onOpenProject: (id: string) => void; onRefresh: () => void;
}) {
  const [workspace, setWorkspace] = useState<ProjectWorkspace | null>(null);
  const [settlements, setSettlements] = useState<SettlementItem[]>([]);
  const [transitions, setTransitions] = useState<Record<string, Array<{ from_status: string | null; to_status: string; source: string; transaction_id: string | null; consensus_timestamp: string | null; reason_code: string; observed_at: string; event_id: string }>>>({});
  const [loadedKey, setLoadedKey] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [projectFilter, setProjectFilter] = useState("ALL");
  const [githubStatus, setGithubStatus] = useState("ALL");

  useEffect(() => {
    if (!projectId) return;
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "/backend-api";
    const controller = new AbortController();
    const get = async <T,>(path: string): Promise<T> => {
      const response = await fetch(`${apiBase}${path}`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`API ${response.status}`);
      return response.json() as Promise<T>;
    };
    void (async () => {
      const [projectResult, settlementResult] = await Promise.allSettled([
        get<ProjectWorkspace>(`/freelancer/projects/${encodeURIComponent(projectId)}`),
        get<{ results: SettlementItem[] }>(`/settlements?project_id=${encodeURIComponent(projectId)}`),
      ]);
      if (controller.signal.aborted) return;
      const failed: string[] = [];
      if (projectResult.status === "fulfilled") setWorkspace(projectResult.value);
      else { setWorkspace(null); failed.push("project detail"); }
      if (settlementResult.status === "fulfilled") {
        setSettlements(settlementResult.value.results);
        const details = await Promise.allSettled(settlementResult.value.results.map((item) => get<SettlementItem & { transitions: Array<{ from_status: string | null; to_status: string; source: string; transaction_id: string | null; consensus_timestamp: string | null; reason_code: string; observed_at: string; event_id: string }> }>(`/settlements/${encodeURIComponent(item.settlement_id)}`)));
        if (controller.signal.aborted) return;
        const transitionMap: typeof transitions = {};
        details.forEach((result, index) => { if (result.status === "fulfilled") transitionMap[settlementResult.value.results[index].settlement_id] = result.value.transitions ?? []; });
        setTransitions(transitionMap);
        if (details.some((result) => result.status === "rejected")) failed.push("settlement history");
      } else { setSettlements([]); setTransitions({}); failed.push("settlements"); }
      setErrors(failed); setLoadedKey(`${projectId}:${revision}`);
    })();
    return () => controller.abort();
  }, [projectId, revision]);

  const loading = Boolean(projectId) && loadedKey !== `${projectId}:${revision}`;
  const viewLoading = loading;
  const needle = query.trim().toLowerCase();
  const visibleProjects = projects.filter((item) => (projectFilter === "ALL" || item.status.toUpperCase() === projectFilter) && `${item.title} ${item.project_id} ${item.status} ${item.provenance}`.toLowerCase().includes(needle));
  const evidence = (workspace?.evidence ?? []).filter((item) => (githubStatus === "ALL" || item.status === githubStatus) && `${item.evidence_id} ${item.source} ${item.status} ${item.repository ?? ""} ${item.reasons.join(" ")}`.toLowerCase().includes(needle));
  const alerts = dashboard.alerts.filter((item) => (statusFilter === "ALL" || item.severity.toUpperCase() === statusFilter) && `${item.title} ${item.type} ${item.trace_id}`.toLowerCase().includes(needle));
  const activity = dashboard.agent_activity.filter((item) => (statusFilter === "ALL" || activityState(item).toUpperCase() === statusFilter) && `${item.summary ?? ""} ${item.event_id} ${item.trace_id} ${item.event_type ?? ""} ${item.agent_id ?? ""}`.toLowerCase().includes(needle));
  const title = navItems.find((item) => item.key === view)?.label ?? "Workspace";
  const sourceEmpty = <div className="empty-state"><Activity size={18} /><span>{viewLoading ? "Chargement des données…" : errors.length ? `Feed indisponible : ${errors.join(", ")}` : "Aucune donnée enregistrée pour ce projet."}</span></div>;
  const detailUnavailable = viewLoading ? "Chargement du dossier projet…" : errors.includes("project detail") ? "API indisponible. Le dossier n’a pas pu être chargé." : "Aucun projet sélectionné.";

  return <>
    {(errors.length > 0 || feedErrors.length > 0) && <div className="notice notice-error" role="alert">Feeds indisponibles : {[...new Set([...errors, ...feedErrors])].join(", ")}. Les valeurs manquantes restent inconnues.<button type="button" onClick={onRefresh}>Réessayer</button></div>}
    {view === "projects" && <section className="panel projects-view">
      <div className="panel-heading"><div><div className="panel-overline">ESPACE PRIVÉ · PROVENANCE CONSERVÉE</div><h2>My Projects</h2><p>Projets accessibles par ce compte, filtrables par statut.</p></div><select className="filter-select" aria-label="Filtrer les projets par statut" value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)}><option value="ALL">Tous les statuts</option>{Array.from(new Set(projects.map((item) => item.status))).map((item) => <option key={item} value={item.toUpperCase()}>{item}</option>)}</select></div>
      <div className="project-list-summary"><div><strong>{projects.length}</strong><span>projet{projects.length === 1 ? "" : "s"} dans votre espace</span></div><span>Visibilité privée · données du compte connecté</span></div>
      {viewLoading && !projects.length ? sourceEmpty : visibleProjects.length ? <div className="project-cards">{visibleProjects.map((item) => <article className="project-tile project-card" key={item.project_id}>
        <span className="project-tile-icon"><BriefcaseBusiness size={21} /></span>
        <div className="project-card-copy"><div className="project-card-title"><strong>{item.title}</strong><span className={`table-status ${item.status.toUpperCase() === "COMPLETED" ? "status-good" : "status-neutral"}`}>{item.status.replaceAll("_", " ")}</span></div>
          <span className="project-card-id">{item.project_id} <i /> {item.provenance}</span>
          <small>{item.description || "Aucune description fournie."}</small><small className="project-updated">Mis à jour le {formatTime(item.updated_at)}</small>
        </div><button className="filter-button" type="button" onClick={() => onOpenProject(item.project_id)}>Ouvrir le dossier <ArrowRight size={14} /></button>
      </article>)}</div> : <div className="empty-state">{projects.length ? "Aucun projet ne correspond aux filtres." : "Aucun projet pour ce compte. Utilise Create Project pour commencer."}</div>}</section>}
    {view === "detail" && (projectId ? <ProjectWorkflowPanel projectId={projectId} user={user} workspace={workspace} loading={viewLoading} error={detailUnavailable} onChanged={onRefresh} /> : <section className="panel"><h2>Project Detail</h2><p>Crée ou sélectionne un projet pour ouvrir son dossier.</p></section>)}
    {view === "agents" && <>
      <section className="stat-grid agents-summary-grid" aria-label="Synthèse des agents">
        <article className="stat-card"><div className="stat-head"><span>Agents enregistrés</span><Bot size={17} /></div><div className="stat-value">{dashboard.agents.length || "UNKNOWN"}</div><div className="stat-foot"><span>Disponibles</span><span>{dashboard.agents.length ? `${dashboard.agents.filter((agent) => agent.health_status === "AVAILABLE").length}/${dashboard.agents.length}` : "UNKNOWN"}</span></div></article>
        <article className="stat-card"><div className="stat-head"><span>Actions récentes</span><Activity size={17} /></div><div className="stat-value">{dashboard.agent_activity.length}</div><div className="stat-foot"><span>Projet actif</span><span>{projectId}</span></div></article>
        <article className="stat-card"><div className="stat-head"><span>Décisions</span><ShieldCheck size={17} /></div><div className="stat-value">{workspace?.decisions.length ?? "UNKNOWN"}</div><div className="stat-foot"><span>Portée transfert</span><span>Local seulement</span></div></article>
        <article className="stat-card"><div className="stat-head"><span>Alertes ouvertes</span><AlertTriangle size={17} /></div><div className="stat-value">{dashboard.alerts.length}</div><div className="stat-foot"><span>Source des événements</span><span>{dashboard.sources.events}</span></div></article>
      </section>
      <section className="panel chart-panel">
        <div className="panel-heading"><div><div className="panel-overline">OBSERVABILITÉ · ÉVÉNEMENTS RÉELS</div><h2>Activité de la plateforme</h2><p>Événements horodatés du projet sélectionné; aucune série synthétique n’est ajoutée.</p></div><span className="chart-period">7 derniers jours</span></div>
        <EventTrendChart events={dashboard.agent_activity} />
      </section>
      <section className="panel">
        <div className="panel-heading"><div><div className="panel-overline">REGISTRE · SANTÉ ISSUE DE L’API</div><h2>AI Control Center</h2><p>État, version, capacités et dernières communications déclarées par chaque agent.</p></div><span className="ai-badge"><Bot size={13} /> {dashboard.agents.length} agents</span></div>
        {dashboard.agents.length ? <div className="data-table-wrap"><table className="data-table">
          <thead><tr><th>Agent</th><th>Version & capacités</th><th>État de santé</th><th>Heartbeat</th><th>Dernière activité</th></tr></thead>
          <tbody>{dashboard.agents.map((agent) => <tr key={agent.id}>
            <td><div className="table-primary"><span className="agent-avatar">{initials(agent.name)}</span><div><strong>{agent.name}</strong><small>{agent.id}</small></div></div></td>
            <td><strong>{agent.agent_version}</strong><small className="table-secondary">{agent.capabilities.join(", ") || "Capacité non déclarée"}</small></td>
            <td><span className={`table-status ${agent.health_status === "AVAILABLE" ? "status-good" : "status-warning"}`}>{agentStateLabel(agent)}</span></td>
            <td>{formatTime(agent.last_heartbeat_at)}</td><td>{formatTime(agent.last_activity_at)}</td>
          </tr>)}</tbody>
        </table></div> : sourceEmpty}
      </section>
      <section className="panel">
        <div className="panel-heading"><div><div className="panel-overline">EXÉCUTIONS & DÉCISIONS</div><h2>Trace des agents</h2><p>Chaque ligne conserve un événement, sa trace et son statut de traitement.</p></div><select className="filter-select" aria-label="Filtrer le statut agent" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">Tous états</option>{["PENDING", "PROCESSING", "PROCESSED", "RETRY", "QUARANTINED", "BLOCKED", "FAILED"].map((s) => <option key={s}>{s}</option>)}</select></div>
        {activity.length ? <div className="data-table-wrap"><table className="data-table event-table">
          <thead><tr><th>Agent / événement</th><th>Détail & identifiants</th><th>État</th><th>Date</th></tr></thead>
          <tbody>{activity.map((item, index) => <tr key={`${item.event_id}-${index}`}>
            <td><strong>{item.agent_id ?? item.actor_id ?? "Orchestrator"}</strong><small className="table-secondary">{item.event_type ?? "Événement projet"}</small></td>
            <td><span>{item.summary || item.event_type || "Détail non fourni"}</span><small className="table-secondary">Event: {item.event_id} · Trace: {item.trace_id}</small></td>
            <td><span className={`table-status ${["PROCESSED"].includes(activityState(item)) ? "status-good" : ["FAILED", "BLOCKED", "QUARANTINED"].includes(activityState(item)) ? "status-danger" : "status-warning"}`}>{activityState(item)}</span></td>
            <td>{formatTime(item.at)}</td>
          </tr>)}</tbody>
        </table></div> : sourceEmpty}
      </section>
      <section className="panel">
        <div className="panel-heading"><div><div className="panel-overline">POLICY OUTPUTS</div><h2>Décisions et raisons</h2><p>Explications émises par la policy, avec leurs références de traçabilité.</p></div></div>
        {workspace?.decisions.length ? <div className="decision-table-wrap"><table className="data-table decision-table">
          <thead><tr><th>Décision</th><th>Raison détaillée</th><th>Policy</th><th>Événement</th></tr></thead>
          <tbody>{workspace.decisions.map((item) => <tr key={item.event_id}><td><span className="table-status status-neutral">{item.decision}</span><small className="table-secondary">{item.reason_code}</small></td><td>{item.reason || "Aucun détail fourni."}</td><td>{item.policy_version}</td><td className="id-cell">{item.event_id}</td></tr>)}</tbody>
        </table></div> : sourceEmpty}
      </section>
    </>}
    {view === "github" && <section className="panel"><div className="panel-heading"><div><div className="panel-overline">GITHUB EVIDENCE · PROVENANCE</div><h2>Pull requests, commits, reviews & CI</h2><p>Dépôt {workspace?.agreement?.github_repository || "non lié"} · profil GitHub {user.github_login || "non renseigné"}. Identité OAuth : non vérifiée.</p></div><select className="filter-select" aria-label="Filtrer les preuves GitHub" value={githubStatus} onChange={(event) => setGithubStatus(event.target.value)}><option value="ALL">Tous verdicts</option>{["SUBMITTED", "UNKNOWN", "VERIFIED", "REJECTED", "PENDING"].map((s) => <option key={s}>{s}</option>)}</select></div>
      {workspace?.agreement?.github_repository && <div className="source-grid"><div><span>Repository</span><strong>{workspace.agreement.github_repository}</strong></div><div><span>Source configurée</span><strong>{dashboard.sources.evidence}</strong></div><div><span>Compte du profil</span><strong>{user.github_login || "UNKNOWN"}</strong></div><div><span>Identity verification</span><strong>Not verified (OAuth)</strong></div></div>}
      {evidence.length ? <div className="data-table-wrap"><table className="data-table evidence-table">
        <thead><tr><th>Référence</th><th>Verdict</th><th>Milestone</th><th>Source & score</th><th>Détails vérifiables</th></tr></thead>
        <tbody>{evidence.map((item) => <tr key={item.evidence_id}>
          <td><strong>{item.evidence_id}</strong><small className="table-secondary">{item.repository ?? "Dépôt inconnu"}</small></td>
          <td><span className={`table-status ${item.status === "VERIFIED" ? "status-good" : item.status === "REJECTED" ? "status-danger" : "status-warning"}`}>{item.status}</span></td>
          <td>{item.milestone_id ?? "Non associé"}</td>
          <td><strong>{item.source}</strong><small className="table-secondary">Score : {item.score === null ? "inconnu" : `${item.score}/100`}</small></td>
          <td><details className="table-details"><summary>Hash, raisons & sources</summary><div className="table-detail-content">
            <p><strong>Hash de preuve</strong><code>{item.proof_hash ?? "Non fourni"}</code></p>
            <p><strong>Événement source</strong><code>{item.source_event_id}</code></p>
            {item.reasons.length > 0 && <ul>{item.reasons.map((reason, index) => <li key={`${item.evidence_id}-${index}`}>{reason}</li>)}</ul>}
            {item.source_refs.length > 0 && <pre>{JSON.stringify(item.source_refs, null, 2)}</pre>}
          </div></details></td>
        </tr>)}</tbody>
      </table></div> : sourceEmpty}
      <div className="notice">Les données TEST_ONLY restent étiquetées comme synthétiques. Les preuves GitHub ne sont authentiques que si la source serveur configurée les a collectées; un identifiant saisi dans le profil ne vérifie pas l’identité.</div></section>}
    {view === "explorer" && <section className="panel">
      <div className="panel-heading"><div><div className="panel-overline">HEDERA MIRROR NODE · {dashboard.sources.hedera}</div><h2>Blockchain Explorer</h2><p>Transactions observées et liens HashScan lorsqu’ils sont fournis par la source.</p></div></div>
      {transactions.length ? <div className="transaction-list">{transactions.map((item) => <article className="transaction-row" key={item.transaction_id}><div><strong>{item.kind.replaceAll("_", " ")}</strong><span>{item.transaction_id}</span></div><span className={`transaction-status status-${item.status.toLowerCase()}`}>{item.status}</span><time>{formatTime(item.consensus_timestamp)}</time>{item.hashscan_url ? <a href={item.hashscan_url} target="_blank" rel="noreferrer" aria-label="Ouvrir dans HashScan"><ExternalLink size={14} /></a> : <span>—</span>}</article>)}</div> : <div className="empty-state"><Blocks size={18} /><span>{feedErrors.includes("Hedera transactions") ? "API des transactions Hedera indisponible. Réessaie pour actualiser le feed." : dashboard.source_status.hedera === "available" ? "Aucune transaction observée pour ce projet." : `Mirror Node indisponible/non configuré (${dashboard.source_status.hedera}). Aucune transaction n’est inventée.`}</span></div>}
      {dashboard.hedera_activity.map((item) => <article className="activity-row" key={item.id}><Blocks size={16} /><div className="activity-copy"><strong>{item.kind} · {item.source}</strong><p>{item.summary}</p><small>{[item.topic_id && `Topic ${item.topic_id}`, item.token_id && `Token ${item.token_id}`, item.contract_id && `Contract ${item.contract_id}`, item.scheduled_transaction_id && `Scheduled transaction ${item.scheduled_transaction_id}`].filter(Boolean).join(" · ") || "Aucun identifiant de topic, token ou contrat fourni"} · Consensus {formatTime(item.consensus_timestamp)}</small></div>{item.hashscan_url && <a href={item.hashscan_url} target="_blank" rel="noreferrer">HashScan</a>}</article>)}
    </section>}
    {view === "wallet" && <>
      <section className="panel"><div className="panel-heading"><div><div className="panel-overline">WALLET & SETTLEMENTS</div><h2>Règlements observés</h2><p>Historique réel en lecture seule depuis l’API ; les lignes simulées sont séparées ci-dessous.</p></div></div>
        {settlements.length ? <div className="data-table-wrap"><table className="data-table settlement-table">
          <thead><tr><th>Règlement</th><th>Statut & réseau</th><th>Transaction</th><th>Dernière observation</th><th>Historique</th></tr></thead>
          <tbody>{settlements.map((item) => <tr key={item.settlement_id}>
            <td><strong>{item.settlement_id}</strong><small className="table-secondary">Source : {item.source ?? "inconnue"}</small></td>
            <td><span className={`table-status ${item.status === "CONFIRMED" ? "status-good" : item.status === "FAILED" ? "status-danger" : "status-warning"}`}>{item.status}</span><small className="table-secondary">{item.network ?? "Réseau inconnu"}</small></td>
            <td className="id-cell">{item.transaction_id ?? "Aucun transaction ID"}</td>
            <td>{formatTime(item.last_observed_at)}<small className="table-secondary">Consensus : {formatTime(item.consensus_timestamp)}</small>{item.last_error_code && <small className="table-error">Erreur : {item.last_error_code}</small>}</td>
            <td><details className="table-details"><summary>{(transitions[item.settlement_id] ?? []).length} transition(s)</summary><div className="table-detail-content">{(transitions[item.settlement_id] ?? []).length ? (transitions[item.settlement_id] ?? []).map((transition) => <p key={transition.event_id}><strong>{transition.from_status ?? "Début"} → {transition.to_status}</strong><span>{transition.source} · {transition.reason_code} · {formatTime(transition.observed_at)}</span><code>{transition.transaction_id ?? transition.event_id}</code></p>) : <p>Aucun historique de transition disponible.</p>}</div></details></td>
          </tr>)}</tbody>
        </table></div> : sourceEmpty}
        {transactions.length > 0 && <div className="transaction-list">{transactions.map((item) => <div className="transaction-row" key={`observed-${item.transaction_id}`}><div><strong>{item.kind.replaceAll("_", " ")}</strong><span>{item.transaction_id}</span></div><span className={`transaction-status status-${item.status.toLowerCase()}`}>{item.status}</span><time>{formatTime(item.consensus_timestamp)}</time>{item.hashscan_url && <a href={item.hashscan_url} target="_blank" rel="noreferrer" aria-label="Ouvrir la transaction dans HashScan"><ExternalLink size={14} /></a>}</div>)}</div>}
      </section>
      {user.demo_only && projectId && workspace && <WalletPayment projectId={projectId} milestones={workspace.milestones} evidence={workspace.evidence} approvals={workspace.approvals} revision={revision} onSubmitted={onRefresh} />}
      {user.demo_only && !workspace && <section className="panel"><p>{viewLoading ? "Chargement du projet de démonstration…" : "Le dossier de démonstration n’est pas disponible."}</p></section>}
      {!user.demo_only && <p className="monitor-footnote">La simulation HBAR est réservée aux comptes DEMO_ONLY locaux. Aucun paiement réel n’est pris en charge.</p>}
    </>}
    {view === "alerts" && <section className="panel"><div className="panel-heading"><div><div className="panel-overline">ALERTES DU PROJET</div><h2>Alerts</h2><p>Sévérité, statut et traçabilité issus du feed projet.</p></div><select className="filter-select" aria-label="Filtrer les alertes" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">Toutes sévérités</option>{["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => <option key={s}>{s}</option>)}</select></div>{alerts.length ? <div className="data-table-wrap"><table className="data-table">
      <thead><tr><th>Alerte</th><th>Sévérité</th><th>État</th><th>Trace</th><th>Créée le</th></tr></thead><tbody>{alerts.map((item) => <tr key={item.id ?? item.trace_id}><td><strong>{item.title}</strong><small className="table-secondary">{item.type.replaceAll("_", " ")}</small></td><td><span className={`table-status severity-${item.severity.toLowerCase()}`}>{item.severity}</span></td><td>{item.resolved_at ? "Résolue" : "Ouverte"}</td><td className="id-cell">{item.trace_id}</td><td>{formatTime(item.created_at)}{item.resolved_at && <small className="table-secondary">Résolue : {formatTime(item.resolved_at)}</small>}</td></tr>)}</tbody></table></div> : sourceEmpty}</section>}
    {view === "audit" && <section className="panel"><div className="panel-heading"><div><div className="panel-overline">JOURNAL PROJET · APPEND-ONLY</div><h2>Audit & Event history</h2><p>Filtre les événements corrélés au projet actif.</p></div><select className="filter-select" aria-label="Filtrer les événements" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">Tous états</option>{["PENDING", "PROCESSING", "PROCESSED", "RETRY", "QUARANTINED", "BLOCKED", "FAILED"].map((s) => <option key={s}>{s}</option>)}</select></div>{activity.length ? <div className="data-table-wrap"><table className="data-table event-table"><thead><tr><th>Type / acteur</th><th>Résumé & corrélation</th><th>État</th><th>Date</th></tr></thead><tbody>{activity.map((item, index) => <tr key={`${item.event_id}-${index}`}><td><strong>{item.kind ?? item.agent_id ?? item.actor_id ?? "Event"}</strong><small className="table-secondary">{item.event_type ?? item.status}</small></td><td><span>{item.summary ?? activityLabel(item)}</span><small className="table-secondary">Event: {item.event_id} · Trace: {item.trace_id} · source: {item.kind ?? "API"}</small></td><td><span className={`table-status ${activityState(item) === "PROCESSED" ? "status-good" : "status-warning"}`}>{activityState(item)}</span></td><td>{formatTime(item.at)}</td></tr>)}</tbody></table></div> : sourceEmpty}</section>}
    {view === "settings" && <section className="panel settings-view"><div className="panel-heading"><div><div className="panel-overline">COMPTE · CONFIGURATION DES SOURCES</div><h2>Paramètres</h2><p>État observé du compte et des connexions. Les secrets restent exclusivement côté serveur.</p></div><button className="filter-button" type="button" onClick={onRefresh}><RefreshCw size={14} /> Actualiser les sources</button></div>
      <div className="settings-section"><div className="settings-section-title"><span className="stat-icon indigo"><Fingerprint size={16} /></span><div><strong>Compte & identité</strong><small>Informations du compte connecté</small></div></div><div className="source-grid settings-grid">
        <div><span>Compte connecté</span><strong>{user.display_name}</strong><small>{user.role}</small></div><div><span>Adresse e-mail</span><strong>{user.email}</strong></div><div><span>Profil GitHub</span><strong>{user.github_login || "Non connecté"}</strong></div><div><span>Compte de démonstration</span><strong>{user.demo_only ? "DEMO_ONLY" : "Non"}</strong><small>{user.demo_only ? "Environnement de test uniquement" : "Compte standard"}</small></div>
      </div></div>
      <div className="settings-section"><div className="settings-section-title"><span className="stat-icon teal"><BriefcaseBusiness size={16} /></span><div><strong>Espace de travail</strong><small>Projet actif et périmètre du compte</small></div></div><div className="source-grid settings-grid">
        <div><span>Projets accessibles</span><strong>{projects.length}</strong></div><div><span>Projet actif</span><strong>{projectId || "Aucun projet sélectionné"}</strong></div>
      </div></div>
      <div className="settings-section"><div className="settings-section-title"><span className="stat-icon violet"><Activity size={16} /></span><div><strong>Sources de données</strong><small>Modes rapportés par l’API pour le projet actif</small></div></div><div className="source-grid settings-grid">
        <div><span>Projets</span><strong>{projectId ? dashboard.sources.project : "Aucun projet sélectionné"}</strong></div><div><span>Événements</span><strong>{projectId ? dashboard.sources.events : "Aucun projet sélectionné"}</strong></div><div><span>Preuves</span><strong>{projectId ? dashboard.sources.evidence : "Aucun projet sélectionné"}</strong></div><div><span>Hedera / Mirror Node</span><strong>{projectId ? dashboard.sources.hedera : "Aucun projet sélectionné"}</strong><small>{projectId ? dashboard.source_status.hedera : "—"}</small></div>
      </div></div>{errors.length > 0 && <p role="alert">Sources indisponibles : {errors.join(", ")}</p>}
      <div className="settings-security-note"><ShieldCheck size={17} /><p><strong>Protection des identifiants</strong><span>Aucune clé privée ni aucun secret fournisseur n’est transmis au navigateur par ce tableau de bord.</span></p></div>
    </section>}
    <footer className="page-footer"><span>{title} · {projectId || "aucun projet sélectionné"}</span><span>Actualiser: utiliser le bouton de la vue, sans données de remplacement</span></footer>
  </>;
}

function DashboardPage() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [data, setData] = useState<Dashboard>(emptyDashboard);
  const [projects, setProjects] = useState<ProjectReference[]>([]);
  const [projectWorkspace, setProjectWorkspace] = useState<ProjectWorkspace | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [registryRevision, setRegistryRevision] = useState(0);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [transactions, setTransactions] = useState<TransactionItem[]>([]);
  const [feedErrors, setFeedErrors] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [activityFilter, setActivityFilter] = useState("ALL");
  const [activeView, setActiveView] = useState<ViewKey>("dashboard");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "/backend-api";
    const controller = new AbortController();
    const get = async <T,>(path: string): Promise<T> => {
      const response = await fetch(`${apiBase}${path}`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`API ${response.status} sur ${path}`);
      return response.json() as Promise<T>;
    };
    const load = async () => {
      setLoading(true);
      setLoadError("");
      setFeedErrors([]);
      try {
        const identity = await get<{ user: AuthUser }>("/auth/me");
        if (controller.signal.aborted) return;
        setUser(identity.user);
        const registry = await get<{ count: number; results: ProjectReference[] }>("/freelancer/projects");
        if (controller.signal.aborted) return;
        setProjects(registry.results);
        setConnected(true);
        if (registry.results.length === 0) {
          setSelectedProjectId(""); setData(emptyDashboard); setProjectWorkspace(null); setTransactions([]); setFeedErrors([]);
          setLastUpdated(new Date().toISOString());
          return;
        }
        const selected = registry.results.find((item) => item.project_id === selectedProjectId) ?? registry.results[0];
        if (selectedProjectId !== selected.project_id) setSelectedProjectId(selected.project_id);
        const base = `/projects/${encodeURIComponent(selected.project_id)}`;
        const dashboard = await get<Dashboard>(`${base}/dashboard`);
        const feeds = await Promise.allSettled([
          get<{ results: ActivityItem[] }>(`${base}/activity`),
          get<{ results: AlertItem[] }>(`${base}/alerts`),
          get<{ results: Hederaitem[] }>(`${base}/hedera/activity`),
          get<{ results: TransactionItem[] }>(`${base}/hedera/transactions`),
          get<ProjectWorkspace>(`/freelancer/projects/${encodeURIComponent(selected.project_id)}`),
        ]);
        if (controller.signal.aborted) return;
        const [activity, alerts, hedera, transactionFeed, projectDetail] = feeds;
        const errors = feeds.flatMap((result, index) => result.status === "rejected" ? [["activity", "alerts", "Hedera activity", "Hedera transactions", "project details"][index]] : []);
        setFeedErrors(errors);
        setProjectWorkspace(projectDetail.status === "fulfilled" ? projectDetail.value : null);
        setData({
          ...dashboard,
          agent_activity: activity.status === "fulfilled" ? activity.value.results.map((item) => ({ ...item, status: item.processing_status && item.processing_status !== "LEGACY" ? item.processing_status : item.status, summary: item.summary || item.event_type || item.processing_status || item.status })) : dashboard.agent_activity,
          alerts: alerts.status === "fulfilled" ? alerts.value.results : dashboard.alerts,
          hedera_activity: hedera.status === "fulfilled" ? hedera.value.results : dashboard.hedera_activity,
        });
        setTransactions(transactionFeed.status === "fulfilled" ? transactionFeed.value.results : []);
        setConnected(true);
        setLastUpdated(new Date().toISOString());
      } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (controller.signal.aborted) return;
      if (error instanceof Error && error.message.includes("API 403 sur /auth/me")) {
        window.location.replace("/login");
        return;
      }
      setData(emptyDashboard);
      setProjectWorkspace(null);
      setTransactions([]);
      setConnected(false);
      setLoadError(error instanceof Error ? error.message : "Impossible de joindre l’API Dev 4.");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [selectedProjectId, registryRevision]);

  const project = data.project;
  const firstName = user?.display_name.split(/\s+/)[0] || "Freelancer";
  const upcomingMilestones = (projectWorkspace?.milestones ?? [])
    .filter((item) => item.target_date && item.status !== "COMPLETED")
    .sort((left, right) => (left.target_date ?? "").localeCompare(right.target_date ?? ""))
    .slice(0, 3);
  const pendingEvidenceCount = projectWorkspace
    ? projectWorkspace.evidence.filter((item) => ["SUBMITTED", "PENDING", "UNKNOWN"].includes(item.status)).length
    : null;
  const availableAgentCount = data.agents.filter((agent) => agent.health_status === "AVAILABLE").length;
  const agentHealthPercent = data.agents.length ? Math.round(availableAgentCount / data.agents.length * 100) : 0;
  const filteredActivity = useMemo(() => data.agent_activity.filter((item) =>
    `${item.summary ?? ""} ${item.agent_id ?? ""} ${item.event_id} ${item.trace_id} ${item.event_type ?? ""} ${item.processing_status ?? ""}`.toLowerCase().includes(query.toLowerCase())
    && (activityFilter === "ALL" || activityState(item).toUpperCase() === activityFilter)), [data.agent_activity, query, activityFilter]);
  const filteredAlerts = data.alerts.filter((item) => `${item.title} ${item.type} ${item.trace_id}`.toLowerCase().includes(query.toLowerCase()));
  const filteredHedera = data.hedera_activity.filter((item) => `${item.kind} ${item.summary} ${item.id}`.toLowerCase().includes(query.toLowerCase()));

  if (!user && loading) return <main className="auth-page"><div className="auth-card">Chargement de la session freelancer…</div></main>;
  if (!user) return <main className="auth-page"><section className="auth-card"><h1>Session requise</h1><p>Connecte-toi pour accéder à tes projets.</p><a className="primary-button auth-submit" href="/login">Ouvrir la connexion</a></section></main>;

  return <div className="app-shell">
    {mobileNavOpen && <button type="button" className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
    <aside className={`sidebar${mobileNavOpen ? " mobile-open" : ""}`}>
      <a href="#overview" className="brand"><span className="brand-mark"><Command size={19} strokeWidth={2.4} /></span><span>FUTURE<span>WORK</span></span></a>
      <div className="workspace-label">WORKSPACE</div>
      <nav className="side-nav" aria-label="Main navigation">
        {navItems.map(({ key, label, icon: Icon }) => <button type="button" className={`nav-link${activeView === key ? " selected" : ""}`} aria-current={activeView === key ? "page" : undefined} onClick={() => { setActiveView(key); setMobileNavOpen(false); }} key={key}>
          <Icon size={17} strokeWidth={1.9} /><span>{label}</span>{label === "AI Control Center" && <span className="nav-dot" />}
        </button>)}
      </nav>
      <div className="sidebar-spacer" />
      <div className="sidebar-help"><div className="help-icon"><CircleHelp size={17} /></div><strong>Need a hand?</strong><p>Explore your project activity and audit history.</p><a href="/backend-api/openapi" target="_blank">API documentation <ArrowRight size={13} /></a></div>
      <div className="profile"><div className="avatar avatar-photo">{user.display_name.split(/\s+/).slice(0,2).map((part) => part[0]).join("").toUpperCase()}</div><div className="profile-copy"><strong>{user.display_name}</strong><span>{user.role}{user.demo_only ? " · DEMO_ONLY" : ""}</span></div><ChevronDown size={15} /></div><FreelancerLogoutButton />
    </aside>

    <main className="main-area" id="overview">
      <header className="topbar">
        <button type="button" className="icon-button mobile-menu-toggle" aria-label={mobileNavOpen ? "Close navigation" : "Open navigation"} onClick={() => setMobileNavOpen((open) => !open)}>{mobileNavOpen ? <X size={18} /> : <Menu size={18} />}</button>
        <div className="breadcrumbs"><span>Workspace</span><span className="crumb-sep">/</span><strong>{navItems.find((item) => item.key === activeView)?.label}</strong></div>
        <div className="top-actions">
          <label className="project-select-label">Projet<select aria-label="Sélectionner un projet" value={selectedProjectId} onChange={(event) => { setData(emptyDashboard); setProjectWorkspace(null); setTransactions([]); setFeedErrors([]); setSelectedProjectId(event.target.value); }}>{projects.length === 0 && <option value="">Aucun projet</option>}{projects.map((item) => <option key={item.project_id} value={item.project_id}>{item.title}</option>)}</select></label>
          <label className="searchbox"><Search size={16} /><input aria-label="Search activity" placeholder="Search activity..." value={query} onChange={(event) => setQuery(event.target.value)} /><kbd>⌘ K</kbd></label>
          <button type="button" className="icon-button" aria-label="Refresh project feeds" onClick={() => setRegistryRevision((revision) => revision + 1)}><RefreshCw size={16} /></button>
          <button type="button" className="icon-button" aria-label="Open alerts" onClick={() => setActiveView("alerts")}><Bell size={17} />{data.alerts.length > 0 && <i />}</button>
          <div className="avatar avatar-photo top-avatar">{initials(user.display_name)}</div>
        </div>
      </header>

      <div className="content-wrap">
        <section className="welcome-row">
          <div><div className="eyebrow">{new Intl.DateTimeFormat("en-GB", { weekday: "long", month: "long", day: "numeric", year: "numeric" }).format(new Date()).toUpperCase()} <span className="live-dot" /></div><h1>Bonjour, {firstName} <span className="wave">✦</span></h1><p>Suivi des projets et preuves rattachés à ton compte.</p></div>
          <div className={`connection-pill ${connected ? "is-connected" : "is-preview"}`}><span className="connection-dot" />{loading ? "Connecting…" : connected ? "Backend connected" : "API unavailable"}<span className="connection-divider" /><span>{connected ? `Project: ${data.sources.project}` : "No fallback data"}</span></div>
        </section>

        {loadError && <div className="notice notice-error" role="status"><span>API indisponible ({loadError}). Aucune donnée de démonstration ne remplace la réponse manquante.</span><button onClick={() => window.location.reload()}>Réessayer</button></div>}
        {loading && <div className="notice" role="status">Loading project, agent, alert and Hedera feeds…</div>}

        {activeView === "dashboard" ? (selectedProjectId ? <>
        <section className="stat-grid" aria-label="Project summary metrics">
          <article className="stat-card"><div className="stat-head"><span>Project progress</span><span className="stat-icon indigo"><Activity size={16} /></span></div><div className="stat-value">{showMetric(project.progress_percent)}{project.progress_percent !== null && <small>%</small>}</div><div className="mini-progress">{project.progress_percent !== null && <span style={{ width: `${project.progress_percent}%` }} />}</div><div className="stat-foot"><span>Overall completion</span><span>{showMetric(project.units.completed)}/{showMetric(project.units.total)} units</span></div></article>
          <article className="stat-card"><div className="stat-head"><span>Milestones</span><span className="stat-icon violet"><Fingerprint size={16} /></span></div><div className="stat-value">{showMetric(project.milestones.completed)}<small>/{showMetric(project.milestones.total)}</small></div><div className="milestone-bars">{Array.from({ length: project.milestones.total ?? 0 }).map((_, i) => <span className={project.milestones.completed !== null && i < project.milestones.completed ? "done" : ""} key={i} />)}</div><div className="stat-foot"><span>Delivery roadmap</span><span>{project.milestones.total !== null && project.milestones.completed !== null ? project.milestones.total - project.milestones.completed : "—"} remaining</span></div></article>
          <article className="stat-card"><div className="stat-head"><span>Evidence verified</span><span className="stat-icon teal"><FileCheck2 size={16} /></span></div><div className="stat-value">{showMetric(project.evidence.verified)}<small>/{showMetric(project.evidence.submitted)}</small></div><div className="mini-progress teal-progress">{metricPercent(project.evidence.verified, project.evidence.submitted) !== null && <span style={{ width: `${metricPercent(project.evidence.verified, project.evidence.submitted)}%` }} />}</div><div className="stat-foot"><span>Preuves en attente</span><span>{showMetric(pendingEvidenceCount)}</span></div></article>
          <article className="stat-card"><div className="stat-head"><span>Settlements</span><span className="stat-icon mint"><Coins size={16} /></span></div><div className="stat-value">{showMetric(project.settlements.confirmed)}<small> confirmed</small></div><div className="settlement-pills"><span><i className="green-dot" /> Confirmed: {showMetric(project.settlements.confirmed)}</span><span><i className="amber-dot" /> {showMetric(project.settlements.pending)} pending</span></div><div className="stat-foot"><span>Transaction monitoring</span><span>{showMetric(project.settlements.failed)} failed</span></div></article>
        </section>

        <section className="panel chart-panel">
          <div className="panel-heading"><div><div className="panel-overline">ACTIVITÉ · DONNÉES OBSERVÉES</div><h2>Événements du projet</h2><p>Volume quotidien issu du journal réel, sans données de démonstration ajoutées.</p></div><span className="chart-period">7 derniers jours</span></div>
          <EventTrendChart events={data.agent_activity} />
        </section>

        <section className="panel">
          <div className="panel-heading"><div><div className="panel-overline">PLANNING · SOURCE PROJET</div><h2>Échéances à venir</h2><p>Dates issues de l’accord et des milestones enregistrés.</p></div><button className="text-link" type="button" onClick={() => setActiveView("detail")}>Project Detail <ArrowRight size={14} /></button></div>
          {projectWorkspace ? <div className="source-grid">
            <div><span>Deadline de l’accord</span><strong>{projectWorkspace.agreement?.target_deadline ?? "Non définie"}</strong></div>
            {upcomingMilestones.length ? upcomingMilestones.map((item) => <div key={item.milestone_id}><span>{item.title} · {item.status}</span><strong>{item.target_date}</strong></div>) : <div><span>Prochain milestone</span><strong>{projectWorkspace.milestones.length ? "Aucune date à venir" : "Plan en attente"}</strong></div>}
          </div> : <div className="empty-state">{feedErrors.includes("project details") ? "Échéances indisponibles : API projet inaccessible." : "Chargement des échéances…"}</div>}
        </section>

        <section className="primary-grid">
          <article className="panel project-panel" id="project">
            <div className="panel-heading"><div><div className="panel-overline">ACTIVE PROJECT</div><h2>{project.title}</h2><p>Project ID: {project.project_id}</p></div><a className="text-link" href="#project-flow">View project <ArrowRight size={14} /></a></div>
            <div className="project-summary"><div className="project-tile"><span className="project-tile-icon"><Blocks size={21} /></span><div><strong>{project.project_id}</strong><span>{project.provenance ?? data.sources.project} · source status below</span></div></div><span className="status-chip"><i /> {project.status.replaceAll("_", " ")}</span></div>
            <p className="project-description">{project.description || "Les indicateurs restent inconnus tant qu’une source métier autorisée ne les fournit pas."}</p>
            <div className="progress-label"><span>Project completion</span><strong>{showMetric(project.progress_percent)}{project.progress_percent !== null ? "%" : ""}</strong></div><div className="large-progress">{project.progress_percent !== null && <span style={{ width: `${project.progress_percent}%` }} />}</div>
            <div className="project-metrics"><div><span>Completed</span><strong>{showMetric(project.units.completed)} <small>units</small></strong></div><div><span>Remaining</span><strong>{project.units.total !== null && project.units.completed !== null ? project.units.total - project.units.completed : "—"} <small>units</small></strong></div><div><span>Evidence</span><strong>{showMetric(project.evidence.verified)} <small>verified</small></strong></div><div><span>Risk level</span><strong><ShieldCheck size={14} /> {project.risk.level}</strong></div></div>
            <div className="project-bottom"><span className="member-text">Project monitoring snapshot</span><span className="updated-text"><Clock3 size={13} /> Updated {formatTime(lastUpdated ?? project.updated_at)}</span></div>
          </article>

          <article className="panel health-panel">
            <div className="panel-heading"><div><div className="panel-overline">SYSTEM OVERVIEW</div><h2>AI Control Center</h2><p>Agent health and project signals</p></div><span className="ai-badge"><Bot size={13} /> DEV 4</span></div>
            <div className="health-layout"><div className="health-ring"><Donut value={agentHealthPercent} label="agent availability" /><div className="health-caption"><span className="health-dot" />{connected ? `${availableAgentCount} of ${data.agents.length} agents available` : "API unavailable"}</div></div><div className="health-list"><div><span>Agent availability</span><strong>{availableAgentCount}/{data.agents.length} <i className={availableAgentCount === data.agents.length ? "ok-tag" : "pending-tag"}>{availableAgentCount === data.agents.length ? "Ready" : "Attention"}</i></strong></div><div><span>Open risks</span><strong>{showMetric(project.risk.open_items)} <i className="low-tag">{project.risk.level}</i></strong></div><div><span>Evidence checks</span><strong>{showMetric(project.evidence.verified)} <i className="pending-tag">{project.evidence.verified === null ? "Unknown" : "Reported"}</i></strong></div><div><span>Settlement status</span><strong>{showMetric(project.settlements.pending)} <i className="pending-tag">{project.settlements.pending === null ? "Unknown" : "Pending"}</i></strong></div></div></div>
            <div className="insight-card"><span className="insight-icon"><Bot size={15} /></span><div><strong>AI insight</strong><p>{project.settlements.pending === null ? "Settlement information has not been received from a source." : project.settlements.pending ? "A settlement is awaiting source confirmation." : "No settlement is currently reported as pending."}</p></div><ArrowRight size={14} /></div>
            <a href="#agents" className="panel-footer-link">Open agent registry <ArrowRight size={14} /></a>
          </article>
        </section>

        <section className="secondary-grid">
          <article className="panel activity-panel" id="audit">
            <div className="panel-heading"><div><div className="panel-overline">PROJECT ACTIVITY · AUDIT TIMELINE</div><h2>Event and agent activity</h2><p>Search by event, agent or trace ID.</p></div><select className="filter-select" aria-label="Filter activity by status" value={activityFilter} onChange={(event) => setActivityFilter(event.target.value)}><option value="ALL">All statuses</option><option value="PENDING">Pending</option><option value="PROCESSING">Processing</option><option value="PROCESSED">Processed</option><option value="RETRY">Retry</option><option value="QUARANTINED">Quarantined</option><option value="BLOCKED">Blocked</option></select></div>
            {filteredActivity.length ? <div className="activity-list">{filteredActivity.slice(0, 8).map((item, index) => {
              const agent = data.agents.find((row) => row.id === item.agent_id);
              return <div className="activity-row" key={`${item.event_id}-${index}`}><div className={`activity-icon activity-${item.agent_id ?? "system"}`}><Bot size={15} /></div><div className="activity-copy"><strong>{agent?.name ?? item.agent_id ?? item.actor_id ?? "System"}<span> · {activityLabel(item)}</span></strong><p>{item.summary}</p><small>{item.event_id} {item.trace_id && <><span>·</span> {item.trace_id}</>}</small></div><time>{formatTime(item.at)}</time></div>;
            })}</div> : <div className="empty-state"><Activity size={18} /><span>No activity matches your search.</span></div>}
            <div className="data-source-note"><span className="source-dot" /> Feed: <strong>{connected ? data.sources.events : "unavailable"}</strong>{data.event_queue && <span> · pending {data.event_queue.pending ?? 0}, processing {data.event_queue.processing ?? 0}, quarantined {data.event_queue.quarantined ?? 0}</span>}{lastUpdated && <span> · refreshed {formatTime(lastUpdated)}</span>}</div>
            <div className="dashboard-decision-heading"><div className="panel-overline">RISK · POLICY</div><h3>Recent decisions</h3></div>
            {projectWorkspace?.decisions.length ? <div className="workflow-list dashboard-decision-list">
              {projectWorkspace.decisions.slice(0, 4).map((decision, index) => <article className="project-tile" key={`${decision.event_id}-${index}`}>
                <div><strong>{decision.decision} · {decision.reason_code}</strong><span>{decision.reason || "No additional decision detail."} · {decision.event_id}</span></div>
              </article>)}
            </div> : <div className="empty-state">{feedErrors.includes("project details") ? "Policy decisions unavailable: project API unreachable." : "No project policy decisions recorded."}</div>}
          </article>

          <article className="panel agents-panel" id="agents">
            <div className="panel-heading"><div><div className="panel-overline">AGENT REGISTRY</div><h2>Team status</h2></div><button className="more-button" aria-label="Agent options">···</button></div>
            <div className="agent-list">{data.agents.map((agent) => {
              const available = agent.health_status === "AVAILABLE";
              const taskBlocked = agent.status === "BLOCKED";
              return <div className="agent-row" key={agent.id} title={agent.capabilities.join(", ")}><div className={`agent-avatar agent-${agent.id}`}>{initials(agent.name)}</div><div className="agent-info"><strong>{agent.name}</strong><span>{agent.agent_version} · last activity {formatTime(agent.last_activity_at)}</span><small>Heartbeat {formatTime(agent.last_heartbeat_at)}</small></div><span className={`agent-state ${available && !taskBlocked ? "healthy" : "warning"}`}><i />{agentStateLabel(agent)}</span></div>;
            })}</div>
            <a href="#agents" className="panel-footer-link">Manage agents <ArrowRight size={14} /></a>
          </article>
        </section>

        <section className="bottom-grid">
          <article className="panel hedera-panel" id="explorer">
            <div className="panel-heading"><div><div className="panel-overline">{data.sources.hedera.toUpperCase()} <span className="green-dot inline" /></div><h2>Blockchain activity</h2><p>Verified observations linked to this project</p></div><a className="text-link" href="#explorer">Explorer <ArrowRight size={14} /></a></div>
            <div className="hedera-table"><div className="table-head"><span>TYPE</span><span>ACTIVITY</span><span>CONSENSUS TIME</span><span>LINK</span></div>{filteredHedera.length ? filteredHedera.slice(0, 8).map((item) => <div className="hedera-row" key={item.id}><span className={`kind-badge ${item.kind.toLowerCase()}`}>{item.kind.replaceAll("_", " ")}</span><strong>{item.summary}</strong><time>{formatTime(item.consensus_timestamp)}</time><a href={item.hashscan_url} target="_blank" rel="noreferrer" aria-label={`Open ${item.kind} in HashScan`}><ExternalLink size={14} /></a></div>) : <div className="empty-state">No Hedera activity matches the search.</div>}</div>
            <div className="data-source-note"><span className="source-dot" /> Data source: <strong>{connected ? data.sources.hedera : "unavailable"}</strong>{data.source_status.hedera !== "available" && <span className="preview-note"> · {data.source_status.hedera}</span>}</div>
          </article>

          <article className="panel alert-panel" id="alerts">
            <div className="panel-heading"><div><div className="panel-overline">NEEDS ATTENTION</div><h2>Active alerts <span className="alert-count">{data.alerts.length}</span></h2></div><button className="more-button" aria-label="Alert options">···</button></div>
            {filteredAlerts.length ? <div className="alert-list">{filteredAlerts.map((alert) => <div className="alert-row" key={alert.id ?? alert.trace_id}><span className={`alert-symbol severity-${alert.severity.toLowerCase()}`}><AlertTriangle size={15} /></span><div><strong>{alert.title}</strong><span>{alert.type.replaceAll("_", " ")} · trace {alert.trace_id} · {formatTime(alert.created_at)}</span></div></div>)}</div> : <div className="all-clear"><span><Check size={17} /></span><div><strong>{query ? "No matching alerts" : "You’re all caught up"}</strong><p>{query ? "Adjust the global search to see other alerts." : "No active alerts need your attention."}</p></div></div>}
          </article>
        </section>

        <section className="monitor-grid" id="settlements">
          <article className="panel">
            <div className="panel-heading"><div><div className="panel-overline">SETTLEMENT MONITORING</div><h2>Transaction status</h2><p>Read-only project feed; settlement actions remain policy-gated.</p></div><span className="ai-badge">{showMetric(project.settlements.pending)} pending</span></div>
            {transactions.length ? <div className="transaction-list">{transactions.map((item) => <div className="transaction-row" key={item.transaction_id}><div><strong>{item.kind.replaceAll("_", " ")}</strong><span>{item.transaction_id}</span></div><span className={`transaction-status status-${item.status.toLowerCase()}`}>{item.status}</span><time>{formatTime(item.consensus_timestamp)}</time><a href={item.hashscan_url} target="_blank" rel="noreferrer" aria-label="Open transaction in HashScan"><ExternalLink size={14} /></a></div>)}</div> : <div className="empty-state"><Coins size={18} /> No transaction feed is available.</div>}
            <div className="monitor-footnote">Read-only observations only. This dashboard does not sign, submit, approve or settle payments.</div>
          </article>
          <article className="panel" id="analytics">
            <div className="panel-heading"><div><div className="panel-overline">PROJECT ANALYTICS</div><h2>Delivery indicators</h2><p>Current snapshot from the configured project source.</p></div><Activity size={17} /></div>
            <div className="analytics-list"><div><span>Units complete</span><strong>{showMetric(project.units.completed)} / {showMetric(project.units.total)}</strong><div className="mini-progress">{metricPercent(project.units.completed, project.units.total) !== null && <span style={{ width: `${metricPercent(project.units.completed, project.units.total)}%` }} />}</div></div><div><span>Milestones complete</span><strong>{showMetric(project.milestones.completed)} / {showMetric(project.milestones.total)}</strong><div className="mini-progress">{metricPercent(project.milestones.completed, project.milestones.total) !== null && <span style={{ width: `${metricPercent(project.milestones.completed, project.milestones.total)}%` }} />}</div></div><div><span>Evidence verified</span><strong>{showMetric(project.evidence.verified)} / {showMetric(project.evidence.submitted)}</strong><div className="mini-progress teal-progress">{metricPercent(project.evidence.verified, project.evidence.submitted) !== null && <span style={{ width: `${metricPercent(project.evidence.verified, project.evidence.submitted)}%` }} />}</div></div></div>
          </article>
        </section>

        <section className="panel source-panel" id="data-sources">
          <div className="panel-heading"><div><div className="panel-overline">SOURCE PROVENANCE</div><h2>Data source status</h2><p>Sources are displayed separately. Missing values stay unknown.</p></div><button className="filter-button" onClick={() => window.location.reload()}>Refresh dashboard</button></div>
          <div className="source-grid"><div><span>Project</span><strong>{connected ? data.sources.project : "unavailable"}</strong></div><div><span>Events</span><strong>{connected ? data.sources.events : "unavailable"}</strong></div><div><span>Evidence / GitHub</span><strong>{connected ? data.sources.evidence : "unavailable"}</strong></div><div><span>Hedera / Mirror Node</span><strong>{connected ? data.sources.hedera : "unavailable"}</strong></div></div>
          <div className="data-source-note"><span className="source-dot" /> {connected ? "Connected to the Dev 4 API. Each source reports its configured mode." : "API unavailable. No local fixture replaces the response."}{feedErrors.length > 0 && <span> · Unavailable feeds: {feedErrors.join(", ")}</span>}{lastUpdated && <span> · Last refresh {formatTime(lastUpdated)}</span>}</div>
        </section>

        <section className="flow-strip" id="project-flow">
          <div className="flow-title"><span className="flow-icon"><Blocks size={17} /></span><div><strong>FUTUREWORK value chain</strong><span>Every milestone is traceable from work to settlement</span></div></div>
          <div className="flow-steps"><span className="flow-step complete"><i>01</i>Engagement</span><ArrowRight size={13} /><span className="flow-step complete"><i>02</i>Work</span><ArrowRight size={13} /><span className="flow-step complete"><i>03</i>Proof</span><ArrowRight size={13} /><span className="flow-step active"><i>04</i>Consensus</span><ArrowRight size={13} /><span className="flow-step"><i>05</i>Settlement</span></div>
        </section>
        </> : <section className="panel empty-registry"><BriefcaseBusiness size={25} /><h2>Aucun projet dans ton espace</h2><p>Le compte connecté n’a aucun projet accessible. Les données de démonstration ne sont pas injectées.</p><button className="filter-button" type="button" onClick={() => setActiveView("create")}>Créer un projet <ArrowRight size={14} /></button></section>
        ) : activeView === "create" ? <FreelancerProjectCreatePanel onChanged={() => setRegistryRevision((revision) => revision + 1)} />
          : <FreelancerDataView key={selectedProjectId} view={activeView} user={user} projects={projects} projectId={selectedProjectId} dashboard={data} transactions={transactions} feedErrors={feedErrors} revision={registryRevision} query={query} onOpenProject={(id) => { setData(emptyDashboard); setProjectWorkspace(null); setTransactions([]); setFeedErrors([]); setSelectedProjectId(id); setActiveView("detail"); }} onRefresh={() => setRegistryRevision((revision) => revision + 1)} />}

        <footer className="page-footer"><span>FUTUREWORK AI Command Center <span>·</span> Built for transparent work</span><span><span className="footer-source"><i /> {connected ? "API connected" : "API unavailable"}</span><span>Version 0.1.0</span></span></footer>
      </div>
    </main>
  </div>;
}

export default DashboardPage;
