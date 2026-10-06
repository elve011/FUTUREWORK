<!-- # Phase 1 — Cadrage Dev 4, contrats et scénarios -->

## Objectif

Définir les contrats et comportements que Dev 4 peut implémenter sans ambiguïté avant de créer le backend. Le périmètre normatif est la section 22 du cahier des charges « Mini-projet 4 — AI Command Center & Monitoring ». La matrice des exigences est dans [`requirements.md`](requirements.md). Cette phase couvre l'orchestration, les modèles de suivi, le dashboard, les alertes, les métriques, le Settlement Monitoring Agent et l'observation Hedera. Le mini-projet doit démarrer seul en mode mock, sans dépendre des applications Dev 1–3.

## Décisions de cadrage

- Les routes exposées sont celles du cahier des charges (`/api/...`). Ajouter un préfixe de version uniquement après accord d'équipe, afin de ne pas casser le contrat fourni.
- Le Command Center contient exactement les quatre agents affichés au cahier: Planner, Evidence, Risk et Settlement.
- Événement accepté une seule fois par `event_id` (idempotence).
- Un `trace_id` identifie le workflow; chaque étape porte un `span_id` et éventuellement un `parent_span_id`.
- Décisions de policy déterministes, données et raison auditées; un LLM ne peut pas autoriser seul un settlement.
- Mirror Node est une source d'observation. Une réponse absente, retardée ou indisponible ne vaut jamais confirmation.
- Dev 4 surveille le settlement; l'émission/signature d'un paiement appartient au composant convenu par l'équipe.
- Bascule mock/live indépendante par source de données (`FW_MODE` par module source); le mode et la provenance sont visibles dans les réponses du dashboard.
- Pas de Celery. Le polling sera un processus séparé, lancé par une commande Django ou un planificateur système, jamais dans une requête web.
- Stockage initial SQLite via Django ORM; aucune dépendance métier à une fonction spécifique SQLite.
- Ne jamais journaliser secrets, clés privées, tokens ou payloads sensibles non nécessaires.

## Statuts

### Workflow

`RECEIVED`, `RUNNING`, `COMPLETED`, `BLOCKED`, `FAILED`

### Décision de policy

`ALLOW`, `BLOCK`, `HUMAN_REVIEW`, `PENDING`

### Settlement

`PENDING`, `CONFIRMED`, `FAILED`, `UNKNOWN`

Ces dimensions sont séparées: une exécution `COMPLETED` peut avoir produit une décision `BLOCK`; un settlement `PENDING` ne signifie pas que le workflow est toujours `RUNNING`.

## Contrat d'événement

Le schéma de travail est [`../api-contracts/event.schema.json`](../api-contracts/event.schema.json). L'enveloppe standard utilise l'identifiant d'événement, le type, le projet, la date UTC, la source et un payload objet. Les quatre types exacts à router dans la démo doivent être alignés sur la page « API Contracts » / catalogue d'événements global; en attendant, ce sont des exemples de travail, pas une taxonomie finale. Exemple:

```json
{
  "event_id": "evt-001",
  "event_type": "MILESTONE_COMPLETED",
  "project_id": "FW-DEMO-001",
  "milestone_id": "milestone-02",
  "occurred_at": "2026-10-01T10:00:00Z",
  "source": "evidence-service",
  "payload": {},
  "correlation_id": "optional-upstream-id"
}
```

Dev 4 produit le `trace_id` à l'ingestion et le retourne au client. `correlation_id` permet de rattacher les traces émises par les services amont sans remplacer le `trace_id` interne.

## Scénarios d'acceptation

Les scénarios et résultats attendus sont dans [`scenarios.md`](scenarios.md). Ils incluent les six familles d'alertes, la démo autonome, le routage de quatre événements mock, les vues de dashboard et les données Hedera en fixtures. L'acceptation FR-A-06 impose l'affichage d'une alerte dans les 10 secondes après l'événement.

## Questions d'intégration à résoudre avec l'équipe

1. Page API Contracts: confirmer les quatre types d'événements utilisés par le routage de démo et l'enveloppe standard exacte.
2. Dev 3: schéma de décision policy, règles bloquantes et preuves obligatoires avant release.
3. Équipe settlement: qui soumet/signe la transaction et quel signal constitue la preuve canonique de confirmation?
4. Hedera: réseau cible, endpoints Mirror Node, identifiants de transaction/scheduled transaction et lien HashScan attendu.
5. Dashboard: règles d'accès, données visibles par rôle et fréquence de rafraîchissement souhaitée.

Tant que ces éléments ne sont pas confirmés, les implémentations utilisent des valeurs mock explicitement étiquetées et ne simulent pas une autorisation réelle.

## Critères de sortie de phase

- Le contrat JSON valide l'exemple nominal et rejette les champs requis absents ou mal typés.
- La matrice des scénarios est acceptée par Dev 1, Dev 2 et Dev 3.
- Les décisions de policy, le parcours de validation humaine et les preuves de settlement sont définis sans ambiguïté.
- Une trace relie événement, agent, décision, transaction et alerte lorsqu'ils existent.
- La démo démarre avec uniquement le mini-projet Dev 4; aucune donnée mock n'est présentée comme donnée Hedera live.
- Les exigences FR-A-01 à FR-A-12 ont un scénario et un endpoint ou écran cible documenté.

## Prochaine phase

Après validation de ces contrats, passer au Jour 2: squelette Django/DRF, configuration SQLite, modèles, interfaces d'adaptateur, fixtures mock et endpoints de santé/ingestion.
