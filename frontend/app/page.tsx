"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import WalletConnect from "./wallet-connect";

const API_BASE = "http://127.0.0.1:8001/api";

type Project = {
  projectId: string;
  title: string;
  description: string;
  client: string;
  worker: string;
  currency: string;
  totalUnits: number;
  status: string;
};

type Agreement = {
  version: number;
  value: string;
  conditions: string;
  deadline: string;
  status: string;
};

type PlanVersion = {
  version: number;
  agreementVersion: number;
  createdAt: string;
  milestones: Milestone[];
};

type WorkUnit = {
  title: string;
  units: number;
  status?: string;
};

type Milestone = {
  milestoneId?: string;
  projectId?: string;
  title: string;
  description?: string;
  units: number;
  deadline: string;
  status?: string;
  workUnits?: WorkUnit[];
};

type PlannerProposal = {
  projectId: string;
  totalUnits: number;
  milestones: Milestone[];
};

type ProjectContract = {
  contractVersion: "1.0";
  projectId: string;
  agreementId: string;
  client: string;
  worker: string;
  totalUnits: number;
  currency: string;
  status: string;
  milestones: {
    milestoneId: string;
    title: string;
    units: number;
    deadline: string;
  }[];
  tokenId: string | null;
};

type Tokenization = {
  projectId: string;
  name: string;
  symbol: string;
  tokenId: string;
  totalSupply: number;
  decimals: number;
  transactionId: string;
  hashscanUrl: string;
  status: string;
  treasuryAccountId?: string;
  unitBalances?: {
    total: number;
    allocated: number;
    released: number;
    remaining: number;
    workerHtsBalance: number;
    treasuryHtsBalance?: number | null;
    localReleasedUnits: number;
    releasedMatchesHtsBalance: boolean;
  };
};

type HederaTransaction = {
  transactionId: string;
  type?: string;
  status: string;
  timestamp: string | null;
  hashscanUrl: string;
};

type HederaTransactionsResponse = {
  projectId: string;
  transactions: HederaTransaction[];
};

type PlannerDeadlineResponse = {
  projectId: string;
  checkedAt: string;
  overdueMilestones: {
    title: string;
    deadline: string;
    status: string;
  }[];
};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const message =
      typeof data?.detail === "string"
        ? data.detail
        : typeof data?.code === "string"
          ? data.code
          : data && typeof data === "object"
            ? Object.entries(data)
                .map(([field, errors]) => {
                  const detail = Array.isArray(errors)
                    ? errors.join(" ")
                    : String(errors);
                  return `${field} : ${detail}`;
                })
                .join(" · ")
            : "";

    throw new Error(message || `Erreur API (${response.status})`);
  }

  return data as T;
}

function splitUnits(total: number, title: string): WorkUnit[] {
  const safeTotal = Math.max(1, Math.floor(total));
  const count = Math.min(3, safeTotal);
  const base = Math.floor(safeTotal / count);
  const remainder = safeTotal % count;

  return Array.from({ length: count }, (_, index) => ({
    title: `${title} — Work package ${index + 1}`,
    units: base + (index < remainder ? 1 : 0),
  }));
}

function formatConsensusTimestamp(timestamp: string | null): string {
  if (!timestamp) return "—";

  const [seconds, nanos = "0"] = timestamp.split(".");
  const milliseconds =
    Number(seconds) * 1000 + Number(nanos.slice(0, 3).padEnd(3, "0"));

  return new Intl.DateTimeFormat("fr-TN", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "Africa/Tunis",
  }).format(new Date(milliseconds));
}

const inputClass =
  "w-full rounded-lg border border-[#263750] bg-[#07101e] px-3 py-2.5 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-cyan-400";

const buttonClass =
  "rounded-lg bg-cyan-400 px-4 py-2.5 text-sm font-bold text-[#04111d] hover:bg-cyan-300 disabled:opacity-50";

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [agreement, setAgreement] = useState<Agreement | null>(null);
  const [agreementHistory, setAgreementHistory] = useState<Agreement[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [planHistory, setPlanHistory] = useState<PlanVersion[]>([]);
  const [contract, setContract] = useState<ProjectContract | null>(null);
  const [tokenization, setTokenization] = useState<Tokenization | null>(null);
  const [transactions, setTransactions] = useState<HederaTransaction[] | null>(
    null,
  );
  const [overdueMilestones, setOverdueMilestones] = useState<
    PlannerDeadlineResponse["overdueMilestones"]
  >([]);
  const [proposal, setProposal] = useState<PlannerProposal | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [showAgreementForm, setShowAgreementForm] = useState(false);

  const [projectDraft, setProjectDraft] = useState({
    title: "",
    description: "",
    client: "",
    worker: "",
    currency: "HBAR",
    totalUnits: "100",
  });

  const [agreementDraft, setAgreementDraft] = useState({
    value: "",
    conditions: "",
    deadline: "",
  });

  const [tokenDraft, setTokenDraft] = useState({
    name: "",
    symbol: "",
  });

  useEffect(() => {
    api<Project[]>("/projects")
      .then((items) => {
        setProjects(items);
        if (items.length > 0) setSelectedId(items[0].projectId);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!selectedId) return;

    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProject(null);
    setAgreement(null);
    setAgreementHistory([]);
    setMilestones([]);
    setPlanHistory([]);
    setContract(null);
    setTokenization(null);
    setTransactions(null);
    setProposal(null);
    setError("");

    Promise.allSettled([
      api<Project>(`/projects/${selectedId}`),
      api<Agreement>(`/projects/${selectedId}/agreement`),
      api<Agreement[]>(`/projects/${selectedId}/agreements/history`),
      api<Milestone[]>(`/projects/${selectedId}/milestones`),
      api<PlanVersion[]>(`/projects/${selectedId}/milestones/history`),
      api<ProjectContract>(`/projects/${selectedId}/contract`),
      api<Tokenization>(`/projects/${selectedId}/token`),
      api<HederaTransactionsResponse>(`/projects/${selectedId}/hedera`),
      api<PlannerDeadlineResponse>(
        `/projects/${selectedId}/planner/deadlines`,
      ),
    ]).then(
      ([
        projectResult,
        agreementResult,
        agreementHistoryResult,
        milestoneResult,
        planHistoryResult,
        contractResult,
        tokenResult,
        transactionResult,
        deadlineResult,
      ]) => {
        if (cancelled) return;

        if (projectResult.status === "fulfilled") {
          const loadedProject = projectResult.value;
          setProject(loadedProject);
          setProjects((current) =>
            current.map((item) =>
              item.projectId === loadedProject.projectId
                ? loadedProject
                : item,
            ),
          );
        }

        if (agreementResult.status === "fulfilled") {
          setAgreement(agreementResult.value);
        }

        if (agreementHistoryResult.status === "fulfilled") {
          setAgreementHistory(agreementHistoryResult.value);
        }

        if (milestoneResult.status === "fulfilled") {
          setMilestones(milestoneResult.value);
        }

        if (planHistoryResult.status === "fulfilled") {
          setPlanHistory(planHistoryResult.value);
        }

        if (contractResult.status === "fulfilled") {
          setContract(contractResult.value);
        }

        if (tokenResult.status === "fulfilled") {
          setTokenization(tokenResult.value);
        } else if (
          contractResult.status === "fulfilled" &&
          contractResult.value.tokenId
        ) {
          setError(
            "Impossible de vérifier le solde du token sur Mirror Node. Les données locales restent visibles; réessaie quand Hedera Testnet répondra.",
          );
        }

        if (transactionResult.status === "fulfilled") {
          setTransactions(transactionResult.value.transactions);
        }

        if (deadlineResult.status === "fulfilled") {
          setOverdueMilestones(deadlineResult.value.overdueMilestones);
        } else {
          setOverdueMilestones([]);
        }
      },
    );

    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");

    try {
      const created = await api<Project>("/projects", {
        method: "POST",
        body: JSON.stringify({
          ...projectDraft,
          totalUnits: Number(projectDraft.totalUnits),
        }),
      });

      setProjects((current) => [created, ...current]);
      setSelectedId(created.projectId);
      setProjectDraft({
        title: "",
        description: "",
        client: "",
        worker: "",
        currency: "HBAR",
        totalUnits: "100",
      });
      setMessage(`Projet ${created.projectId} créé.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Création impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function createAgreement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedId) return;

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const created = await api<Agreement>(
        `/projects/${selectedId}/agreement`,
        {
          method: "POST",
          body: JSON.stringify(agreementDraft),
        },
      );

      setAgreement(created);
      setAgreementHistory((current) => [
        created,
        ...current.map((item) => ({ ...item, status: "SUPERSEDED" })),
      ]);
      setShowAgreementForm(false);

      const [updatedProject, updatedContract] = await Promise.all([
        api<Project>(`/projects/${selectedId}`),
        api<ProjectContract>(`/projects/${selectedId}/contract`),
      ]);

      setProject(updatedProject);
      setContract(updatedContract);
      setProjects((current) =>
        current.map((item) =>
          item.projectId === updatedProject.projectId ? updatedProject : item,
        ),
      );
      setMessage(`Work Agreement v${created.version} activé.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Création impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function generatePlan() {
    if (!selectedId) return;

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const result = await api<PlannerProposal>(
        `/projects/${selectedId}/planner/plan`,
        {
          method: "POST",
          body: "{}",
        },
      );

      setProposal(result);
      setMessage(
        "Proposition générée. Vérifie les unités avant de l’enregistrer.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Planification impossible.");
    } finally {
      setBusy(false);
    }
  }

  function editMilestone(
    index: number,
    field: "title" | "deadline" | "units",
    value: string,
  ) {
    setProposal((current) => {
      if (!current) return current;

      const updated = [...current.milestones];
      const old = updated[index];

      const units =
        field === "units" ? Math.max(1, Number(value) || 1) : old.units;
      const title = field === "title" ? value : old.title;

      updated[index] = {
        ...old,
        [field]: field === "units" ? units : value,
        ...(field === "units" || field === "title"
          ? { workUnits: splitUnits(units, title) }
          : {}),
      };

      return { ...current, milestones: updated };
    });
  }

  async function savePlan() {
    if (!selectedId || !proposal) return;

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const saved = await api<Milestone[]>(
        `/projects/${selectedId}/milestones`,
        {
          method: milestones.length > 0 ? "PUT" : "POST",
          body: JSON.stringify(proposal.milestones),
        },
      );

      setMilestones(saved);
      setProposal(null);

      const updatedPlanHistory = await api<PlanVersion[]>(
        `/projects/${selectedId}/milestones/history`,
      );
      setPlanHistory(updatedPlanHistory);

      const [updatedContract, deadlineData] = await Promise.all([
        api<ProjectContract>(`/projects/${selectedId}/contract`),
        api<PlannerDeadlineResponse>(
          `/projects/${selectedId}/planner/deadlines`,
        ),
      ]);

      setContract(updatedContract);
      setOverdueMilestones(deadlineData.overdueMilestones);
      setMessage("Milestones et Work Units enregistrés.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Enregistrement impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function createToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedId) return;

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const created = await api<Tokenization>(
        `/projects/${selectedId}/tokenize`,
        {
          method: "POST",
          body: JSON.stringify({
            name: tokenDraft.name,
            symbol: tokenDraft.symbol,
          }),
        },
      );

      setTokenization(created);

      const [updatedContract, transactionData] = await Promise.all([
        api<ProjectContract>(`/projects/${selectedId}/contract`),
        api<HederaTransactionsResponse>(`/projects/${selectedId}/hedera`),
      ]);

      setContract(updatedContract);
      setTransactions(transactionData.transactions);
      setMessage(`Token ${created.tokenId} créé sur Hedera Testnet.`);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "La création du token a échoué.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function updateMilestoneStatus(milestone: Milestone, value: string) {
    if (!selectedId || !milestone.milestoneId) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api<Milestone>(
        `/projects/${selectedId}/milestones/${encodeURIComponent(milestone.milestoneId.replace("M-", ""))}/status`,
        { method: "PATCH", body: JSON.stringify({ status: value }) },
      );
      setMilestones((current) => current.map((item) =>
        item.milestoneId === updated.milestoneId ? updated : item,
      ));
      const [deadlineData, updatedContract] = await Promise.all([
        api<PlannerDeadlineResponse>(`/projects/${selectedId}/planner/deadlines`),
        api<ProjectContract>(`/projects/${selectedId}/contract`),
      ]);
      setOverdueMilestones(deadlineData.overdueMilestones);
      setContract(updatedContract);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Modification du statut impossible.");
    } finally {
      setBusy(false);
    }
  }

  function exportProjectContract() {
    if (!contract) return;

    const file = new Blob([JSON.stringify(contract, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(file);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${contract.projectId}-contract.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const proposedTotal =
    proposal?.milestones.reduce((sum, item) => sum + item.units, 0) ?? 0;

  const completedUnits = milestones
    .filter((item) => item.status?.toUpperCase() === "COMPLETED")
    .reduce((sum, item) => sum + item.units, 0);

  const progress = project?.totalUnits
    ? Math.min(100, Math.round((completedUnits / project.totalUnits) * 100))
    : 0;

  const plannedWorkUnits = milestones.reduce(
    (sum, item) =>
      sum +
      (item.workUnits ?? []).reduce((unitSum, unit) => unitSum + unit.units, 0),
    0,
  );

  const locallyAllocatedUnits = milestones.reduce(
    (sum, item) =>
      sum +
      (item.workUnits ?? [])
        .filter((unit) => unit.status?.toUpperCase() === "ALLOCATED")
        .reduce((unitSum, unit) => unitSum + unit.units, 0),
    0,
  );

  const locallyReleasedUnits = milestones.reduce(
    (sum, item) =>
      sum +
      (item.workUnits ?? [])
        .filter((unit) => unit.status?.toUpperCase() === "RELEASED")
        .reduce((unitSum, unit) => unitSum + unit.units, 0),
    0,
  );

  const allocatedUnits =
    tokenization?.unitBalances?.allocated ?? locallyAllocatedUnits;
  const releasedUnits =
    tokenization?.unitBalances?.released ?? locallyReleasedUnits;
  const remainingUnits =
    tokenization?.unitBalances?.remaining ??
    (project
      ? Math.max(
          0,
          project.totalUnits - locallyAllocatedUnits - locallyReleasedUnits,
        )
      : 0);

  const tokenId = tokenization?.tokenId || contract?.tokenId || null;
  const tokenSupply =
    tokenization?.totalSupply ??
    (contract?.tokenId ? contract.totalUnits : null);
  const tokenHashscanUrl =
    tokenization?.hashscanUrl ||
    (tokenId ? `https://hashscan.io/testnet/token/${tokenId}` : null);
  const tokenCreationPending = tokenization?.status === "PENDING";

  const navItems = [
    ["#overview", "Project Overview"],
    ["#agreement", "Work Agreement"],
    ["#milestones", "Milestones"],
    ["#work-units", "Work Units"],
    ["#tokenization", "Tokenization"],
    ["#wallet", "Wallet"],
    ["#transactions", "Hedera Transactions"],
  ];

  return (
    <main className="min-h-screen bg-[#050b16] text-slate-100">
      <div className="flex min-h-screen">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-white/[0.08] bg-[#070e1b] p-4 lg:flex">
          <div className="flex items-center gap-3 px-2 py-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/10 text-sm font-black text-cyan-200">
              FW
            </span>
            <div>
              <p className="text-xs font-extrabold tracking-[0.15em]">
                FUTUREWORK
              </p>
              <p className="text-[10px] text-slate-500">Dev 1</p>
            </div>
          </div>

          <nav className="mt-8 grid gap-1" aria-label="Dashboard Dev 1">
            {navItems.map(([href, label], index) => (
              <a
                key={href}
                href={href}
                className={`rounded-lg px-3 py-2.5 text-xs transition ${
                  index === 0
                    ? "border border-cyan-300/15 bg-cyan-300/[0.08] font-semibold text-cyan-200"
                    : "text-slate-400 hover:bg-white/[0.04] hover:text-white"
                }`}
              >
                {label}
              </a>
            ))}
          </nav>

          <p className="mt-auto rounded-lg border border-white/[0.07] bg-[#0a1424] p-3 text-[10px] leading-5 text-slate-500">
            Project & Tokenization
          </p>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="border-b border-white/[0.08] bg-[#08111f] px-5 py-5 md:px-8">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-cyan-300">
                  FutureWork · Dev 1
                </p>
                <h1 className="mt-1 text-2xl font-bold text-white">
                  Project & Tokenization
                </h1>
              </div>

              <label className="grid gap-1">
                <span className="text-[10px] uppercase tracking-wider text-slate-500">
                  Projet
                </span>
                <select
                  value={selectedId}
                  onChange={(event) => setSelectedId(event.target.value)}
                  className={`${inputClass} min-w-56`}
                >
                  <option value="">Choisir un projet</option>
                  {projects.map((item) => (
                    <option key={item.projectId} value={item.projectId}>
                      {item.projectId} · {item.title}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </header>

          <div className="mx-auto max-w-7xl space-y-5 px-4 py-6 md:px-8">
            {error && (
              <div
                role="alert"
                className="rounded-lg border border-rose-400/20 bg-rose-400/[0.08] p-3 text-sm text-rose-200"
              >
                {error}
              </div>
            )}

            {message && (
              <div
                role="status"
                className="rounded-lg border border-emerald-400/20 bg-emerald-400/[0.07] p-3 text-sm text-emerald-200"
              >
                {message}
              </div>
            )}

            <section
              id="overview"
              className="scroll-mt-4 rounded-xl border border-white/[0.08] bg-[#0a1424] p-4 md:p-5"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <PanelTitle title="Project Overview" />
                <button
                  type="button"
                  disabled={!contract || busy}
                  onClick={exportProjectContract}
                  className={buttonClass}
                >
                  Exporter le contrat JSON
                </button>
              </div>
              {project ? (
                <>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <DataCard label="Project ID" value={project.projectId} />
                    <DataCard label="Client" value={project.client} />
                    <DataCard label="Worker" value={project.worker} />
                    <DataCard label="Statut" value={project.status} />
                  </div>
                  <div className="mt-4 rounded-lg border border-white/[0.07] bg-[#07101e] p-4">
                    <div className="flex justify-between gap-3 text-xs">
                      <span className="text-slate-400">Progression</span>
                      <span className="font-semibold text-cyan-200">
                        {progress}%
                      </span>
                    </div>
                    <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800">
                      <div
                        className="h-full rounded-full bg-cyan-400"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  </div>
                </>
              ) : (
                <p className="mt-3 text-sm text-slate-500">
                  Sélectionne un projet pour afficher son aperçu.
                </p>
              )}
            </section>

            <section
              id="agreement"
              className="scroll-mt-4 rounded-xl border border-white/[0.08] bg-[#0a1424] p-4 md:p-5"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <PanelTitle title="Work Agreement" />
                {agreement && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setShowAgreementForm((visible) => !visible)}
                    className={buttonClass}
                  >
                    {showAgreementForm ? "Annuler" : "Créer une nouvelle version"}
                  </button>
                )}
              </div>
              {agreement && project && !showAgreementForm ? (
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <DataCard label="Conditions" value={agreement.conditions} />
                  <DataCard
                    label="Valeur"
                    value={`${agreement.value} ${project.currency}`}
                  />
                  <DataCard label="Échéance" value={agreement.deadline} />
                  <DataCard
                    label="Unités totales"
                    value={String(project.totalUnits)}
                  />
                  <DataCard
                    label="Statut"
                    value={`${agreement.status} · v${agreement.version}`}
                  />
                </div>
              ) : project ? (
                <form
                  onSubmit={createAgreement}
                  className="mt-4 grid gap-3 sm:grid-cols-2"
                >
                  <Field label={`Valeur (${project.currency})`}>
                    <input
                      required
                      type="number"
                      min="0.01"
                      step="0.01"
                      value={agreementDraft.value}
                      onChange={(event) =>
                        setAgreementDraft({
                          ...agreementDraft,
                          value: event.target.value,
                        })
                      }
                      className={inputClass}
                    />
                  </Field>
                  <Field label="Échéance">
                    <input
                      required
                      type="date"
                      value={agreementDraft.deadline}
                      onChange={(event) =>
                        setAgreementDraft({
                          ...agreementDraft,
                          deadline: event.target.value,
                        })
                      }
                      className={inputClass}
                    />
                  </Field>
                  <div className="sm:col-span-2">
                    <Field label="Conditions">
                      <textarea
                        required
                        rows={3}
                        value={agreementDraft.conditions}
                        onChange={(event) =>
                          setAgreementDraft({
                            ...agreementDraft,
                            conditions: event.target.value,
                          })
                        }
                        className={inputClass}
                      />
                    </Field>
                  </div>
                  <button disabled={busy} className={buttonClass}>
                    {agreement
                      ? "Activer la nouvelle version"
                      : "Créer le Work Agreement"}
                  </button>
                </form>
              ) : (
                <p className="mt-3 text-sm text-slate-500">
                  Les informations de l’agreement s’afficheront ici.
                </p>
              )}
              {agreementHistory.length > 0 && (
                <details className="mt-4 rounded-lg border border-white/[0.07] bg-[#07101e] p-3">
                  <summary className="cursor-pointer text-xs font-semibold text-cyan-200">
                    Historique des versions ({agreementHistory.length})
                  </summary>
                  <div className="mt-3 grid gap-2">
                    {agreementHistory.map((item) => (
                      <div key={item.version} className="grid gap-1 border-t border-white/[0.06] pt-2 text-xs sm:grid-cols-4">
                        <span>Version {item.version} · {item.status}</span>
                        <span>{item.value} {project?.currency}</span>
                        <span>Échéance : {item.deadline}</span>
                        <span className="break-words text-slate-400">{item.conditions}</span>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </section>

            <section
              id="milestones"
              className="scroll-mt-4 rounded-xl border border-white/[0.08] bg-[#0a1424] p-4 md:p-5"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <PanelTitle title="Milestones" />
                <button
                  disabled={busy || !agreement}
                  onClick={generatePlan}
                  className={buttonClass}
                >
                  Proposer un plan
                </button>
              </div>

              {proposal && (
                <div className="mt-4 rounded-lg border border-cyan-300/15 bg-[#07101e] p-3">
                  <p className="text-xs text-slate-400">
                    Proposition modifiable · unités proposées : {proposedTotal}{" "}
                    / {proposal.totalUnits}
                  </p>
                  <div className="mt-3 grid gap-2">
                    {proposal.milestones.map((item, index) => (
                      <div
                        key={`${item.title}-${index}`}
                        className="grid gap-2 sm:grid-cols-[1fr_100px_160px]"
                      >
                        <input
                          aria-label="Titre du milestone"
                          value={item.title}
                          onChange={(event) =>
                            editMilestone(index, "title", event.target.value)
                          }
                          className={inputClass}
                        />
                        <input
                          aria-label="Unités du milestone"
                          type="number"
                          min="1"
                          value={item.units}
                          onChange={(event) =>
                            editMilestone(index, "units", event.target.value)
                          }
                          className={inputClass}
                        />
                        <input
                          aria-label="Échéance du milestone"
                          type="date"
                          value={item.deadline}
                          onChange={(event) =>
                            editMilestone(index, "deadline", event.target.value)
                          }
                          className={inputClass}
                        />
                      </div>
                    ))}
                  </div>
                  <button
                    disabled={busy || proposedTotal !== proposal.totalUnits}
                    onClick={savePlan}
                    className={`${buttonClass} mt-3`}
                  >
                    Enregistrer le plan
                  </button>
                </div>
              )}

              {milestones.length > 0 ? (
                <div className="mt-4 overflow-x-auto rounded-lg border border-white/[0.07]">
                  <table className="w-full min-w-[600px] text-left text-xs">
                    <thead className="bg-[#07101e] text-slate-400">
                      <tr>
                        <th className="px-3 py-3">Milestone</th>
                        <th className="px-3 py-3">Unités</th>
                        <th className="px-3 py-3">Échéance</th>
                        <th className="px-3 py-3">Statut</th>
                      </tr>
                    </thead>
                    <tbody>
                      {milestones.map((item, index) => {
                        const isOverdue = overdueMilestones.some(
                          (overdue) =>
                            overdue.title === item.title &&
                            overdue.deadline === item.deadline,
                        );

                        return (
                          <tr
                            key={`${item.title}-${index}`}
                            className="border-t border-white/[0.06]"
                          >
                            <td className="px-3 py-3 font-medium text-slate-100">
                              {item.title}
                            </td>
                            <td className="px-3 py-3 text-cyan-200">
                              {item.units}
                            </td>
                            <td className="px-3 py-3 text-slate-300">
                              {item.deadline}
                            </td>
                            <td className="px-3 py-3">
                              <select
                                aria-label={`Statut de ${item.title}`}
                                value={isOverdue ? "OVERDUE" : item.status || "PLANNED"}
                                onChange={(event) => void updateMilestoneStatus(item, event.target.value)}
                                disabled={busy || isOverdue}
                                className="rounded border border-[#263750] bg-[#07101e] px-2 py-1 text-xs text-slate-200 disabled:opacity-60"
                              >
                                <option value="PLANNED">PLANNED</option>
                                <option value="IN_PROGRESS">IN_PROGRESS</option>
                                <option value="COMPLETED">COMPLETED</option>
                                {isOverdue && <option value="OVERDUE">EN RETARD</option>}
                              </select>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="mt-3 text-sm text-slate-500">
                  Aucun milestone enregistré.
                </p>
              )}
              {planHistory.length > 0 && (
                <details className="mt-4 rounded-lg border border-white/[0.07] bg-[#07101e] p-3">
                  <summary className="cursor-pointer text-xs font-semibold text-cyan-200">
                    Historique des plans ({planHistory.length})
                  </summary>
                  <div className="mt-3 grid gap-2">
                    {planHistory.map((item) => (
                      <div key={item.version} className="border-t border-white/[0.06] pt-2 text-xs text-slate-300">
                        Plan v{item.version} · Agreement v{item.agreementVersion} · {new Date(item.createdAt).toLocaleString("fr-TN")}
                        <ul className="mt-1 list-inside list-disc text-slate-400">
                          {item.milestones.map((entry, index) => (
                            <li key={`${entry.title}-${index}`}>{entry.title} — {entry.units} unités — {entry.deadline}</li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </section>

            <section
              id="work-units"
              className="scroll-mt-4 rounded-xl border border-white/[0.08] bg-[#0a1424] p-4 md:p-5"
            >
              <PanelTitle title="Work Units" />
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <DataCard
                  label="Total"
                  value={String(project?.totalUnits ?? "—")}
                />
                <DataCard
                  label="Allouées"
                  value={project ? String(allocatedUnits) : "—"}
                />
                <DataCard
                  label="Restantes"
                  value={project ? String(remainingUnits) : "—"}
                />
                <DataCard
                  label="Libérées"
                  value={project ? String(releasedUnits) : "—"}
                />
              </div>
              {tokenization?.unitBalances && !tokenization.unitBalances.releasedMatchesHtsBalance && (
                <p className="mt-3 text-xs text-amber-200">
                  Mirror Node : le worker détient {tokenization.unitBalances.workerHtsBalance} HTS, alors que {tokenization.unitBalances.localReleasedUnits} unité(s) sont marquées libérées dans le plan. Vérifie les transferts Hedera.
                </p>
              )}
              {project && plannedWorkUnits !== project.totalUnits && (
                <p className="mt-3 text-xs text-slate-500">
                  Unités planifiées dans les Work Units : {plannedWorkUnits} /{" "}
                  {project.totalUnits}
                </p>
              )}
            </section>

            <section
              id="tokenization"
              className="scroll-mt-4 rounded-xl border border-white/[0.08] bg-[#0a1424] p-4 md:p-5"
            >
              <PanelTitle title="Tokenization" />

              {tokenId ? (
                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <DataCard label="Token ID" value={tokenId} />
                  <DataCard
                    label="Supply"
                    value={tokenSupply === null ? "Non disponible" : String(tokenSupply)}
                  />
                  <DataCard
                    label="Décimales"
                    value={
                      tokenization
                        ? String(tokenization.decimals)
                        : "Non disponible"
                    }
                  />
                  <div className="rounded-lg border border-white/[0.07] bg-[#07101e] p-3">
                    <p className="text-[10px] uppercase tracking-wider text-slate-500">
                      HashScan
                    </p>
                    {tokenHashscanUrl ? (
                      <a
                        href={tokenHashscanUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 inline-block text-sm font-semibold text-cyan-200 underline"
                      >
                        Voir le token
                      </a>
                    ) : (
                      <p className="mt-2 text-sm text-slate-500">
                        Lien indisponible
                      </p>
                    )}
                  </div>
                </div>
              ) : tokenCreationPending ? (
                <p className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/[0.07] p-3 text-sm text-amber-100">
                  La création du token est en attente de vérification. Ne
                  relance pas la création avant d’avoir vérifié Hedera Testnet.
                </p>
              ) : selectedId ? (
                <form
                  onSubmit={createToken}
                  className="mt-4 grid gap-3 sm:grid-cols-2"
                >
                  <Field label="Nom du token">
                    <input
                      required
                      maxLength={100}
                      value={tokenDraft.name}
                      onChange={(event) =>
                        setTokenDraft({
                          ...tokenDraft,
                          name: event.target.value,
                        })
                      }
                      className={inputClass}
                      placeholder="Ex. FutureWork Project"
                    />
                  </Field>
                  <Field label="Symbole du token">
                    <input
                      required
                      maxLength={20}
                      value={tokenDraft.symbol}
                      onChange={(event) =>
                        setTokenDraft({
                          ...tokenDraft,
                          symbol: event.target.value.toUpperCase(),
                        })
                      }
                      className={inputClass}
                      placeholder="Ex. FW004"
                    />
                  </Field>
                  <p className="text-xs leading-5 text-slate-400 sm:col-span-2">
                    Supply initial : {project?.totalUnits ?? "—"} unité(s), avec
                    0 décimale, selon le total du projet. Cette action crée un
                    token sur Hedera Testnet et utilise des HBAR de test.
                  </p>
                  <button
                    type="submit"
                    disabled={busy || !project || !tokenDraft.name.trim() || !tokenDraft.symbol.trim()}
                    className={buttonClass}
                  >
                    {busy ? "Création en cours…" : "Créer le token HTS"}
                  </button>
                </form>
              ) : (
                <p className="mt-3 text-sm text-slate-500">
                  Sélectionne un projet pour afficher sa tokenisation.
                </p>
              )}
            </section>

            <section
              id="wallet"
              className="scroll-mt-4 rounded-xl border border-white/[0.08] bg-[#0a1424] p-4 md:p-5"
            >
              <PanelTitle title="Wallet" />
              <div className="mt-4">
                <WalletConnect
                  key={selectedId}
                  projectId={selectedId}
                  tokenId={tokenization?.tokenId}
                  workerAccountId={project?.worker ?? ""}
                  treasuryAccountId={tokenization?.treasuryAccountId ?? ""}
                  treasuryTokenBalance={tokenization?.unitBalances?.treasuryHtsBalance}
                  initiallyAllocatedUnits={allocatedUnits}
                  onAllocated={(updatedMilestones) =>
                    setMilestones(updatedMilestones)
                  }
                  onReleased={async (updatedMilestones) => {
                    setMilestones(updatedMilestones);
                    const [tokenResult, transactionResult] = await Promise.all([
                      api<Tokenization>(`/projects/${selectedId}/token`),
                      api<HederaTransactionsResponse>(`/projects/${selectedId}/hedera`),
                    ]);
                    setTokenization(tokenResult);
                    setTransactions(transactionResult.transactions);
                  }}
                />
              </div>
            </section>

            <section
              id="transactions"
              className="scroll-mt-4 rounded-xl border border-white/[0.08] bg-[#0a1424] p-4 md:p-5"
            >
              <PanelTitle title="Hedera Transactions" />
              {transactions && transactions.length > 0 ? (
                <div className="mt-4 overflow-x-auto rounded-lg border border-white/[0.07]">
                  <table className="w-full min-w-[720px] text-left text-xs">
                    <thead className="bg-[#07101e] text-slate-400">
                      <tr>
                        <th className="px-3 py-3">Transaction ID</th>
                        <th className="px-3 py-3">Type</th>
                        <th className="px-3 py-3">Statut</th>
                        <th className="px-3 py-3">Timestamp</th>
                      </tr>
                    </thead>
                    <tbody>
                      {transactions.map((item) => (
                        <tr
                          key={item.transactionId}
                          className="border-t border-white/[0.06]"
                        >
                          <td className="px-3 py-3 font-mono text-cyan-200">
                            <a
                              href={item.hashscanUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="underline"
                            >
                              {item.transactionId}
                            </a>
                          </td>
                          <td className="px-3 py-3">{item.type || "—"}</td>
                          <td className="px-3 py-3">{item.status}</td>
                          <td className="px-3 py-3">
                            {formatConsensusTimestamp(item.timestamp)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="mt-3 text-sm text-slate-500">
                  {transactions === null
                    ? "Données de transactions non disponibles."
                    : "Aucune transaction Hedera enregistrée."}
                </p>
              )}
            </section>

            <section
              id="create-project"
              className="scroll-mt-4 rounded-xl border border-white/[0.08] bg-[#0a1424] p-4 md:p-5"
            >
              <PanelTitle title="Créer un projet" />
              <form
                onSubmit={createProject}
                className="mt-4 grid gap-3 md:grid-cols-2"
              >
                <Field label="Titre">
                  <input
                    required
                    value={projectDraft.title}
                    onChange={(event) =>
                      setProjectDraft({
                        ...projectDraft,
                        title: event.target.value,
                      })
                    }
                    className={inputClass}
                  />
                </Field>
                <Field label="Description">
                  <input
                    value={projectDraft.description}
                    onChange={(event) =>
                      setProjectDraft({
                        ...projectDraft,
                        description: event.target.value,
                      })
                    }
                    className={inputClass}
                  />
                </Field>
                <Field label="Client Account ID">
                  <input
                    required
                    value={projectDraft.client}
                    onChange={(event) =>
                      setProjectDraft({
                        ...projectDraft,
                        client: event.target.value,
                      })
                    }
                    className={inputClass}
                  />
                </Field>
                <Field label="Worker Account ID">
                  <input
                    required
                    value={projectDraft.worker}
                    onChange={(event) =>
                      setProjectDraft({
                        ...projectDraft,
                        worker: event.target.value,
                      })
                    }
                    className={inputClass}
                  />
                </Field>
                <Field label="Devise">
                  <input
                    required
                    maxLength={4}
                    value={projectDraft.currency}
                    onChange={(event) =>
                      setProjectDraft({
                        ...projectDraft,
                        currency: event.target.value.toUpperCase(),
                      })
                    }
                    className={inputClass}
                  />
                </Field>
                <Field label="Total units">
                  <input
                    required
                    min="1"
                    type="number"
                    value={projectDraft.totalUnits}
                    onChange={(event) =>
                      setProjectDraft({
                        ...projectDraft,
                        totalUnits: event.target.value,
                      })
                    }
                    className={inputClass}
                  />
                </Field>
                <button disabled={busy} className={buttonClass}>
                  Créer le projet
                </button>
              </form>
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}

function PanelTitle({ title }: { title: string }) {
  return <h2 className="text-base font-bold text-white">{title}</h2>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid min-w-0 gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </span>
      {children}
    </label>
  );
}

function DataCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-white/[0.07] bg-[#07101e] p-3">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-1 break-words text-sm font-semibold text-slate-100">
        {value}
      </p>
    </div>
  );
}
