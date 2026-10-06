"use client";

import { useEffect, useState } from "react";
import { postWithCsrf } from "../lib/auth";

type Milestone = {
  milestone_id: string;
  title: string;
  planned_work_units: number | null;
  completed_work_units: number | null;
  status: string;
};
type Evidence = { milestone_id: string | null; status: string; source: string };
type Approval = { kind: string; decision: string; milestone_id?: string | null };
type MilestonePayment = { status: string; transaction_id: string | null; last_error_code: string | null };
type PaymentConfig = {
  network: string;
  operator_account_id: string;
  recipient_account_id: string;
  amount_hbar: string;
  enabled: boolean;
  reason: string | null;
  milestone_payments: Record<string, MilestonePayment>;
};
type PaymentResult = { settlement_id: string; transaction_id: string; hashscan_url: string; amount_hbar: string };

function isPaymentConfig(value: unknown): value is PaymentConfig {
  if (!value || typeof value !== "object") return false;
  const config = value as Partial<PaymentConfig>;
  return config.network === "testnet"
    && typeof config.operator_account_id === "string"
    && typeof config.recipient_account_id === "string"
    && config.amount_hbar === "0.1"
    && typeof config.enabled === "boolean"
    && (config.reason === null || typeof config.reason === "string")
    && Boolean(config.milestone_payments)
    && typeof config.milestone_payments === "object";
}

export default function WalletPayment({
  projectId,
  milestones,
  evidence,
  approvals,
  revision,
  onSubmitted,
}: {
  projectId: string;
  milestones: Milestone[];
  evidence: Evidence[];
  approvals: Approval[];
  revision: number;
  onSubmitted: () => void;
}) {
  const [loadedConfig, setLoadedConfig] = useState<{ projectId: string; config: PaymentConfig } | null>(null);
  const [loadedConfigError, setLoadedConfigError] = useState<{ projectId: string; error: string } | null>(null);
  const [message, setMessage] = useState("");
  const [busyMilestone, setBusyMilestone] = useState("");
  const config = loadedConfig?.projectId === projectId ? loadedConfig.config : null;
  const configError = loadedConfigError?.projectId === projectId ? loadedConfigError.error : "";

  useEffect(() => {
    let active = true;
    void fetch(`/backend-api/freelancer/projects/${encodeURIComponent(projectId)}/hedera/testnet/config`, {
      cache: "no-store",
      credentials: "include",
    }).then(async (response) => {
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(`Configuration paiement API ${response.status}`);
      if (!isPaymentConfig(body)) throw new Error("Réponse de configuration testnet invalide.");
      if (active) {
        setLoadedConfig({ projectId, config: body });
        setLoadedConfigError(null);
      }
    }).catch((error: unknown) => {
      if (active) setLoadedConfigError({ projectId, error: error instanceof Error ? error.message : "Configuration Hedera indisponible." });
    });
    return () => { active = false; };
  }, [projectId, revision]);

  const isEvidenceVerified = (milestoneId: string) => evidence.some((item) =>
    item.milestone_id === milestoneId && item.status === "VERIFIED");
  const isApproved = (milestoneId: string) => approvals.some((item) =>
    item.kind === "MILESTONE" && item.milestone_id === milestoneId && item.decision === "APPROVED");
  const isEligible = (item: Milestone) => item.status === "COMPLETED"
    && item.planned_work_units !== null
    && item.completed_work_units === item.planned_work_units
    && isEvidenceVerified(item.milestone_id)
    && isApproved(item.milestone_id);

  async function sendPayment(milestone: Milestone) {
    if (!config?.enabled || !isEligible(milestone) || config.milestone_payments[milestone.milestone_id]) return;
    const confirmed = window.confirm(
      `Confirmer le transfert réel de ${config.amount_hbar} HBAR sur Hedera TESTNET ?\n\n`
      + `Depuis : ${config.operator_account_id}\nVers : ${config.recipient_account_id}\nJalon : ${milestone.title}\n\n`
      + "Cette action est irréversible sur le testnet. Le backend utilisera la clé locale configurée ; elle ne sera pas envoyée au navigateur.",
    );
    if (!confirmed) return;

    setBusyMilestone(milestone.milestone_id);
    setMessage("");
    try {
      const result = await postWithCsrf(
        `/backend-api/freelancer/projects/${encodeURIComponent(projectId)}/hedera/testnet/transfers`,
        { milestone_id: milestone.milestone_id, amount_hbar: config.amount_hbar, confirm: true },
      ) as PaymentResult;
      setMessage(`Transfert accepté par Hedera : ${result.amount_hbar} HBAR · ${result.transaction_id}`);
      onSubmitted();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Transfert testnet impossible.");
      onSubmitted();
    } finally {
      setBusyMilestone("");
    }
  }

  return <section className="panel wallet-simulation" aria-labelledby="wallet-payment-title">
    <div className="panel-heading">
      <div>
        <div className="panel-overline">SIGNATURE SERVEUR · TESTNET SEULEMENT</div>
        <h2 id="wallet-payment-title">Paiement HBAR testnet</h2>
        <p>Chaque action envoie réellement 0,1 HBAR depuis le compte testnet configuré vers le destinataire ci-dessous.</p>
      </div>
    </div>
    <div className="wallet-demo-balance">
      <span>Réseau verrouillé</span><strong>Hedera <small>TESTNET</small></strong>
      <span>Depuis {config?.operator_account_id || "compte testnet non configuré"} · vers {config?.recipient_account_id || "destinataire testnet non configuré"}</span>
      <span>Clé privée conservée uniquement dans l’environnement du backend local ; jamais dans le navigateur.</span>
    </div>
    {configError && <p className="simulation-message" role="alert">{configError}</p>}
    {config && !config.enabled && <p className="simulation-message" role="status">
      Transfert désactivé · {config.reason ?? "Configuration incomplète"}. Le backend doit recevoir les trois variables HEDERA testnet locales avant son démarrage.
    </p>}
    {message && <p className="payment-message" role="status">{message}</p>}
    <div className="simulation-table-wrap">
      <table className="simulation-table">
        <thead><tr><th>Jalon</th><th>Unités</th><th>Preuve</th><th>Approbation</th><th>Paiement testnet</th></tr></thead>
        <tbody>{milestones.map((milestone) => {
          const hasEvidence = isEvidenceVerified(milestone.milestone_id);
          const hasApproval = isApproved(milestone.milestone_id);
          const payment = config?.milestone_payments[milestone.milestone_id];
          const transactionId = payment?.transaction_id;
          return <tr key={milestone.milestone_id}>
            <td><strong>{milestone.title}</strong><small>{milestone.milestone_id}</small></td>
            <td>{milestone.completed_work_units ?? "—"}/{milestone.planned_work_units ?? "—"}</td>
            <td><span className={`simulation-status ${hasEvidence ? "status-success" : "status-failed"}`}>{hasEvidence ? "Vérifiée" : "Manquante"}</span>
              {evidence.find((item) => item.milestone_id === milestone.milestone_id && item.status === "VERIFIED")?.source === "TEST_ONLY" && <small>Preuve démo synthétique</small>}
            </td>
            <td><span className={`simulation-status ${hasApproval ? "status-success" : "status-failed"}`}>{hasApproval ? "Approuvé" : "En attente"}</span></td>
            <td>{payment && payment.status !== "FAILED"
              ? <div><span className={`simulation-status ${payment.status === "SUBMITTED_BY_OWNER" ? "status-success" : ""}`}>{payment.status === "SUBMITTED_BY_OWNER" ? "Envoyé · reçu Hedera SUCCESS" : payment.status === "UNKNOWN" ? "Résultat incertain · vérifier avant tout nouvel envoi" : payment.status}</span>
                {payment.last_error_code && <small>{payment.last_error_code}</small>}
                {transactionId && <a className="payment-hashscan-link" href={`https://hashscan.io/testnet/transaction/${transactionId.replace("@", "-")}`} target="_blank" rel="noreferrer">Ouvrir dans HashScan</a>}
              </div>
              : <button className="filter-button" type="button" disabled={!config?.enabled || !isEligible(milestone) || busyMilestone !== ""} onClick={() => void sendPayment(milestone)}>
                {busyMilestone === milestone.milestone_id ? "Envoi testnet…" : payment ? "Réessayer 0,1 HBAR" : "Envoyer 0,1 HBAR"}
              </button>}
            </td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <p className="monitor-footnote">Les preuves et approbations préchargées sont marquées DEMO_ONLY / TEST_ONLY ; elles servent uniquement au test local du bouton de paiement. Un reçu SUCCESS est conservé comme soumis par le propriétaire ; le Mirror Node garde la responsabilité de l’observation/finalité séparée.</p>
  </section>;
}
