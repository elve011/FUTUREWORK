"use client";

import { useEffect, useState } from "react";

const API_BASE = "http://127.0.0.1:8001/api";

type WalletSigner = {
  getAccountId: () => { toString: () => string };
  getLedgerId: () => { toString: () => string };
};

type HashPackExtension = {
  id: string;
  name?: string;
  available: boolean;
};

type WalletSession = {
  namespaces?: Record<string, { accounts?: string[] }>;
};

type WalletClientEvents = {
  on?: (event: string, callback: (...args: unknown[]) => void) => void;
  off?: (event: string, callback: (...args: unknown[]) => void) => void;
};

type DAppConnector = {
  extensions: HashPackExtension[];
  signers: WalletSigner[];
  walletConnectClient?: WalletClientEvents;
  init: (options?: { logger?: "error" | "warn" | "info" | "debug" }) => Promise<void>;
  connectExtension: (extensionId: string) => Promise<WalletSession>;
  disconnectAll: () => Promise<void>;
  signAndExecuteTransaction: (params: {
    signerAccountId: string;
    transactionList: string;
  }) => Promise<unknown>;
};

type WalletIntegration = {
  dAppConnector: DAppConnector;
  requestExtensionDiscovery: () => void;
};

type AssociationResponse = {
  associated: boolean;
};

type AssociationState = "unknown" | "not-associated" | "pending" | "associated";
type AllocatedMilestone = {
  title: string;
  description?: string;
  units: number;
  deadline: string;
  status?: string;
  workUnits?: Array<{
    title: string;
    description?: string;
    units: number;
    status?: string;
  }>;
};

type WalletGlobal = typeof globalThis & {
  __futureWorkHashPackConnectorPromise?: Promise<WalletIntegration>;
};

const walletGlobal = globalThis as WalletGlobal;

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function getWalletIntegration(): Promise<WalletIntegration> {
  if (walletGlobal.__futureWorkHashPackConnectorPromise) {
    return walletGlobal.__futureWorkHashPackConnectorPromise;
  }

  const integrationPromise = (async () => {
    const projectId = process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID;

    if (!projectId) {
      throw new Error(
        "NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID est absent de frontend/.env.local.",
      );
    }

    const [hederaWalletConnect, hederaSdk] = await Promise.all([
      import("@hashgraph/hedera-wallet-connect"),
      import("@hiero-ledger/sdk"),
    ]);
    const metadata = {
      name: "FutureWork",
      description: "Project & Tokenization sur Hedera Testnet",
      url: window.location.origin,
      icons: [],
    };

    const dAppConnector = new hederaWalletConnect.DAppConnector(
      metadata,
      hederaSdk.LedgerId.TESTNET,
      projectId,
      Object.values(hederaWalletConnect.HederaJsonRpcMethod),
      [
        hederaWalletConnect.HederaSessionEvent.ChainChanged,
        hederaWalletConnect.HederaSessionEvent.AccountsChanged,
      ],
      [hederaWalletConnect.HederaChainId.Testnet],
      "error",
    ) as unknown as DAppConnector;

    await dAppConnector.init({ logger: "error" });

    return {
      dAppConnector,
      requestExtensionDiscovery: hederaWalletConnect.extensionQuery,
    };
  })();

  walletGlobal.__futureWorkHashPackConnectorPromise = integrationPromise;

  try {
    return await integrationPromise;
  } catch (error) {
    if (walletGlobal.__futureWorkHashPackConnectorPromise === integrationPromise) {
      delete walletGlobal.__futureWorkHashPackConnectorPromise;
    }
    throw error;
  }
}

function findHashPackExtension(connector: DAppConnector) {
  return connector.extensions.find(
    (extension) =>
      extension.available &&
      `${extension.name ?? ""} ${extension.id}`.toLowerCase().includes("hashpack"),
  );
}

function getNativeTestnetAccountId(connector: DAppConnector): string {
  const signer = connector.signers.find((item) =>
    item.getLedgerId().toString().toLowerCase().includes("testnet"),
  );
  return signer?.getAccountId().toString() ?? "";
}

async function readAssociation(
  projectId: string,
  accountId: string,
): Promise<boolean> {
  const params = new URLSearchParams({ accountId });
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/token/association?${params}`,
  );
  const data = (await response.json().catch(() => null)) as
    | AssociationResponse
    | { detail?: string; code?: string }
    | null;

  if (!response.ok) {
    const detail = data && "detail" in data ? data.detail : undefined;
    const code = data && "code" in data ? data.code : undefined;
    throw new Error(detail || code || "Vérification de l’association impossible.");
  }

  return Boolean(data && "associated" in data && data.associated);
}

export default function WalletConnect({
  projectId,
  tokenId,
  workerAccountId,
  treasuryAccountId,
  treasuryTokenBalance,
  initiallyAllocatedUnits,
  onAllocated,
  onReleased,
}: {
  projectId: string;
  tokenId?: string;
  workerAccountId: string;
  treasuryAccountId: string;
  treasuryTokenBalance?: number | null;
  initiallyAllocatedUnits: number;
  onAllocated: (milestones: AllocatedMilestone[]) => void;
  onReleased: (milestones: AllocatedMilestone[]) => Promise<void>;
}) {
  const [hederaAccountId, setHederaAccountId] = useState("");
  const [associationRecord, setAssociationRecord] = useState<{
    key: string;
    state: AssociationState;
  }>();
  const [transactionId, setTransactionId] = useState("");
  const [allocationMessage, setAllocationMessage] = useState("");
  const [error, setError] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [associating, setAssociating] = useState(false);
  const [allocating, setAllocating] = useState(false);
  const [transferring, setTransferring] = useState(false);
  const [allocatedUnits, setAllocatedUnits] = useState(initiallyAllocatedUnits);
  const [transferMessage, setTransferMessage] = useState("");
  const associationKey = `${projectId}|${tokenId ?? ""}|${hederaAccountId}`;
  const association =
    associationRecord?.key === associationKey
      ? associationRecord.state
      : "unknown";

  useEffect(() => {
    // The token balance arrives asynchronously after this component mounts.
    // Keep the transfer amount in sync with the server-confirmed allocation.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAllocatedUnits(initiallyAllocatedUnits);
  }, [initiallyAllocatedUnits]);

  useEffect(() => {
    let cancelled = false;
    let connector: DAppConnector | undefined;
    let walletClient: WalletClientEvents | undefined;
    const syncAccount = () => {
      if (!cancelled && connector) {
        setHederaAccountId(getNativeTestnetAccountId(connector));
      }
    };

    void getWalletIntegration()
      .then(({ dAppConnector }) => {
        if (cancelled) return;
        connector = dAppConnector;
        walletClient = connector.walletConnectClient;
        setHederaAccountId(getNativeTestnetAccountId(connector));
        walletClient?.on?.("session_event", syncAccount);
        walletClient?.on?.("session_update", syncAccount);
        walletClient?.on?.("session_delete", syncAccount);
      })
      .catch(() => {
        // Les erreurs de configuration sont affichées quand l'utilisateur se connecte.
      });

    return () => {
      cancelled = true;
      walletClient?.off?.("session_event", syncAccount);
      walletClient?.off?.("session_update", syncAccount);
      walletClient?.off?.("session_delete", syncAccount);
    };
  }, []);

  useEffect(() => {
    if (!projectId || !tokenId || !hederaAccountId) return;

    let cancelled = false;
    void readAssociation(projectId, hederaAccountId)
      .then((associated) => {
        if (!cancelled) {
          setAssociationRecord({
            key: associationKey,
            state: associated ? "associated" : "not-associated",
          });
        }
      })
      .catch((caughtError: Error) => {
        if (!cancelled) setError(caughtError.message);
      });

    return () => {
      cancelled = true;
    };
  }, [associationKey, hederaAccountId, projectId, tokenId]);

  async function connectWallet() {
    setError("");
    setConnecting(true);

    try {
      const { dAppConnector, requestExtensionDiscovery } =
        await getWalletIntegration();

      if (hederaAccountId) {
        await dAppConnector.disconnectAll();
        setHederaAccountId("");
        return;
      }

      await wait(300);
      let hashPack = findHashPackExtension(dAppConnector);
      if (!hashPack) {
        requestExtensionDiscovery();
        await wait(500);
        hashPack = findHashPackExtension(dAppConnector);
      }

      if (!hashPack) {
        throw new Error(
          "HashPack n’est pas détecté sur localhost:3001. Dans Chrome, ouvre Extensions > HashPack > Accès au site, autorise localhost:3001, puis actualise la page.",
        );
      }

      await dAppConnector.connectExtension(hashPack.id);
      const accountId = getNativeTestnetAccountId(dAppConnector);
      if (!accountId) {
        throw new Error(
          "HashPack a répondu, mais aucun compte Hedera Testnet n’a été reçu. Vérifie que le compte sélectionné dans HashPack est bien sur Testnet.",
        );
      }
      setHederaAccountId(accountId);
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "La connexion à l’extension HashPack a échoué.",
      );
    } finally {
      setConnecting(false);
    }
  }

  async function associateToken() {
    if (!projectId || !tokenId || !hederaAccountId) return;
    setError("");
    setAssociating(true);

    try {
      if (association === "pending") {
        const associated = await readAssociation(projectId, hederaAccountId);
        setAssociationRecord({
          key: associationKey,
          state: associated ? "associated" : "pending",
        });
        return;
      }

      const [{ dAppConnector }, hederaSdk, walletConnect] = await Promise.all([
        getWalletIntegration(),
        import("@hiero-ledger/sdk"),
        import("@hashgraph/hedera-wallet-connect"),
      ]);
      const transaction = new hederaSdk.TokenAssociateTransaction()
        .setAccountId(hederaAccountId)
        .setTokenIds([tokenId]);

      setAssociationRecord({ key: associationKey, state: "pending" });
      let result: unknown;
      try {
        result = await dAppConnector.signAndExecuteTransaction({
          signerAccountId: `hedera:testnet:${hederaAccountId}`,
          transactionList: walletConnect.transactionToBase64String(transaction),
        });
      } catch (caughtError) {
        setAssociationRecord({
          key: associationKey,
          state: "not-associated",
        });
        throw caughtError;
      }
      const transactionResult = result as {
        transactionId?: string;
        result?: { transactionId?: string };
      };
      setTransactionId(
        transactionResult.transactionId ??
          transactionResult.result?.transactionId ??
          "",
      );

      for (let attempt = 0; attempt < 8; attempt += 1) {
        await wait(2500);
        try {
          if (await readAssociation(projectId, hederaAccountId)) {
            setAssociationRecord({
              key: associationKey,
              state: "associated",
            });
            return;
          }
        } catch (caughtError) {
          setAssociationRecord({ key: associationKey, state: "pending" });
          throw caughtError;
        }
      }
      setAssociationRecord({ key: associationKey, state: "pending" });
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "L’association du token a échoué ou a été refusée.",
      );
    } finally {
      setAssociating(false);
    }
  }

  async function allocateWorkUnits() {
    if (!projectId || !tokenId || !hederaAccountId) return;
    setError("");
    setAllocationMessage("");
    setTransferMessage("");
    setAllocating(true);

    try {
      const response = await fetch(
        `${API_BASE}/projects/${encodeURIComponent(projectId)}/token/allocate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ accountId: hederaAccountId }),
        },
      );
      const data = (await response.json().catch(() => null)) as
        | {
            allocatedUnits?: number;
            workUnits?: AllocatedMilestone[];
          }
        | { detail?: string; code?: string }
        | null;

      if (!response.ok) {
        const detail = data && "detail" in data ? data.detail : undefined;
        const code = data && "code" in data ? data.code : undefined;
        throw new Error(detail || code || "Allocation impossible.");
      }

      if (data && "workUnits" in data && Array.isArray(data.workUnits)) {
        onAllocated(data.workUnits);
        setAllocatedUnits(data.allocatedUnits ?? 0);
        setAllocationMessage(
          `${data.allocatedUnits ?? 0} unités affectées au worker dans le plan. Il reste à signer leur transfert HTS depuis le compte trésorerie.`,
        );
      }
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Allocation impossible.",
      );
    } finally {
      setAllocating(false);
    }
  }

  async function transferAllocatedUnits() {
    if (!projectId || !tokenId || !workerAccountId || !treasuryAccountId) return;
    if (hederaAccountId !== treasuryAccountId) {
      setError(`Connecte le compte trésorerie ${treasuryAccountId} dans HashPack pour signer le transfert.`);
      return;
    }
    if (allocatedUnits <= 0) {
      setError("Aucune Work Unit n’attend de transfert. Connecte le compte worker et alloue d’abord les unités.");
      return;
    }
    if (treasuryTokenBalance === undefined || treasuryTokenBalance === null) {
      setError("Le solde HTS de la trésorerie n’est pas vérifiable sur Mirror Node. Réessaie avant de signer.");
      return;
    }
    if (treasuryTokenBalance !== undefined && treasuryTokenBalance !== null && treasuryTokenBalance < allocatedUnits) {
      setError(`La trésorerie ne détient que ${treasuryTokenBalance} HTS, alors que ${allocatedUnits} sont alloués. Vérifie le solde du token.`);
      return;
    }

    setError("");
    setTransferMessage("");
    setTransferring(true);

    try {
      if (!(await readAssociation(projectId, workerAccountId))) {
        throw new Error("Le compte worker doit d’abord être associé au token sur Hedera Testnet.");
      }

      const [{ dAppConnector }, hederaSdk, walletConnect] = await Promise.all([
        getWalletIntegration(),
        import("@hiero-ledger/sdk"),
        import("@hashgraph/hedera-wallet-connect"),
      ]);
      const transaction = new hederaSdk.TransferTransaction()
        .addTokenTransfer(tokenId, treasuryAccountId, -allocatedUnits)
        .addTokenTransfer(tokenId, workerAccountId, allocatedUnits);

      const result = (await dAppConnector.signAndExecuteTransaction({
        signerAccountId: `hedera:testnet:${treasuryAccountId}`,
        transactionList: walletConnect.transactionToBase64String(transaction),
      })) as {
        transactionId?: string;
        result?: { transactionId?: string };
      };
      const submittedTransactionId =
        result.transactionId ?? result.result?.transactionId ?? "";
      if (!submittedTransactionId) {
        throw new Error("HashPack n’a pas retourné l’identifiant de la transaction. Vérifie son statut dans Hedera Transactions.");
      }
      setTransactionId(submittedTransactionId);

      let confirmation: {
        workUnits?: AllocatedMilestone[];
        detail?: string;
      } | null = null;
      for (let attempt = 0; attempt < 12; attempt += 1) {
        if (attempt > 0) await wait(2500);
        const response = await fetch(
          `${API_BASE}/projects/${encodeURIComponent(projectId)}/token/confirm-release`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              accountId: workerAccountId,
              transactionId: submittedTransactionId,
            }),
          },
        );
        const data = (await response.json().catch(() => null)) as
          | { workUnits?: AllocatedMilestone[]; detail?: string; code?: string }
          | null;
        if (response.ok && data && "workUnits" in data && Array.isArray(data.workUnits)) {
          confirmation = data;
          break;
        }
        if (response.status !== 409 || data?.code !== "TRANSFER_NOT_CONFIRMED") {
          throw new Error(data?.detail || "La confirmation du transfert a échoué.");
        }
      }

      if (!confirmation?.workUnits) {
        throw new Error("Transaction soumise à HashPack, mais pas encore confirmée par Mirror Node. Vérifie son statut Hedera avant toute nouvelle tentative.");
      }

      setAllocatedUnits(0);
      setTransferMessage(
        `${allocatedUnits} HTS transférés au worker et confirmés sur Hedera Testnet. Transaction : ${submittedTransactionId}`,
      );
      onAllocated(confirmation.workUnits);
      try {
        await onReleased(confirmation.workUnits);
      } catch {
        setError("Le transfert est confirmé sur Hedera, mais l’actualisation du tableau de bord a échoué. Recharge le projet.");
      }
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Le transfert HTS a échoué ou a été refusé dans HashPack.",
      );
    } finally {
      setTransferring(false);
    }
  }

  const accountLabel = hederaAccountId || "Non connecté";
  const associationLabel =
    association === "associated"
      ? "Confirmée sur Hedera Testnet"
      : association === "pending"
        ? "En attente de confirmation sur Hedera"
        : association === "not-associated"
          ? "Non confirmée"
          : hederaAccountId && tokenId
            ? "Vérification…"
            : "Non confirmée";

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="rounded-lg border border-white/[0.08] bg-[#070f1d] p-4">
        <p className="text-xs uppercase tracking-wide text-slate-400">
          Compte connecté · Hedera Testnet
        </p>
        <p className="mt-2 break-all font-semibold text-white">{accountLabel}</p>
        <button
          type="button"
          onClick={connectWallet}
          disabled={connecting}
          className="mt-4 rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-slate-950 disabled:opacity-60"
        >
          {connecting
            ? "Connexion à HashPack…"
            : hederaAccountId
              ? "Déconnecter HashPack"
              : "Connecter HashPack"}
        </button>
        {!hederaAccountId && (
          <p className="mt-3 text-sm leading-5 text-slate-400">
            La demande s’ouvre directement dans l’extension HashPack. Aucun QR
            code ni lien à copier.
          </p>
        )}
      </div>

      <div className="rounded-lg border border-white/[0.08] bg-[#070f1d] p-4">
        <p className="text-xs uppercase tracking-wide text-slate-400">
          Association du token
        </p>
        <p className="mt-2 font-semibold text-white">{associationLabel}</p>
        {hederaAccountId && hederaAccountId !== workerAccountId && (
          <p className="mt-2 text-xs text-amber-200">
            Pour associer le token et affecter les unités au plan, connecte le compte worker : {workerAccountId}.
          </p>
        )}
        {hederaAccountId && tokenId && association !== "associated" && (
          <button
            type="button"
            onClick={associateToken}
            disabled={associating || association === "unknown" || hederaAccountId !== workerAccountId}
            className="mt-4 rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-slate-950 disabled:opacity-60"
          >
            {associating
              ? "Vérification sur Hedera…"
              : association === "pending"
                ? "Vérifier l’association"
                : "Associer le token"}
          </button>
        )}
        {hederaAccountId &&
          tokenId &&
          association === "associated" &&
          hederaAccountId === workerAccountId && (
            <button
              type="button"
              onClick={allocateWorkUnits}
              disabled={allocating}
              className="mt-4 rounded-lg border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 font-semibold text-cyan-100 disabled:opacity-60"
            >
              {allocating ? "Allocation…" : "Allouer les Work Units"}
            </button>
          )}
        {hederaAccountId &&
          tokenId &&
          treasuryAccountId &&
          hederaAccountId === treasuryAccountId && (
            <div className="mt-4">
              <button
                type="button"
                onClick={transferAllocatedUnits}
                disabled={transferring || allocatedUnits <= 0 || treasuryTokenBalance == null || treasuryTokenBalance < allocatedUnits}
                className="rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-slate-950 disabled:opacity-60"
              >
                {transferring
                  ? "Transfert et confirmation Hedera…"
                  : `Transférer ${allocatedUnits} HTS au worker`}
              </button>
              {allocatedUnits > 0 && (
                <p className="mt-2 text-xs leading-5 text-slate-400">
                  {treasuryTokenBalance == null
                    ? "Le solde de trésorerie doit être vérifié sur Mirror Node avant le transfert."
                    : treasuryTokenBalance < allocatedUnits
                      ? `Solde trésorerie insuffisant : ${treasuryTokenBalance} HTS disponibles sur ${allocatedUnits} nécessaires.`
                      : `HashPack demandera au compte trésorerie de signer l’envoi de ${allocatedUnits} HTS vers ${workerAccountId}.`}
                </p>
              )}
            </div>
          )}
        {hederaAccountId &&
          tokenId &&
          treasuryAccountId &&
          hederaAccountId !== treasuryAccountId &&
          hederaAccountId === workerAccountId && (
            <p className="mt-3 text-xs leading-5 text-slate-400">
              Après l’association et l’allocation, change le compte sélectionné dans HashPack vers la trésorerie ({treasuryAccountId}), reconnecte-le, puis signe le transfert ici.
            </p>
          )}
        {tokenId && !treasuryAccountId && (
          <p role="alert" className="mt-3 text-xs leading-5 text-red-300">
            Le compte trésorerie n’est pas configuré côté backend. Ajoute HEDERA_ACCOUNT_ID puis recharge le serveur.
          </p>
        )}
        {!tokenId && (
          <p className="mt-3 text-sm text-slate-400">
            Crée d’abord le token de ce projet.
          </p>
        )}
        {transactionId && (
          <p className="mt-3 break-all text-xs text-slate-400">
            ID de transaction d’association : {transactionId}
          </p>
        )}
        {allocationMessage && (
          <p role="status" className="mt-3 text-xs leading-5 text-cyan-100">
            {allocationMessage}
          </p>
        )}
        {transferMessage && (
          <p role="status" className="mt-3 break-all text-xs leading-5 text-cyan-100">
            {transferMessage}
          </p>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-300 sm:col-span-2">
          {error}
        </p>
      )}
    </div>
  );
}
