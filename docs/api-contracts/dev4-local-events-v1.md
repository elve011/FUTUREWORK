# Contrats locaux de test Dev 4 — v1.0 provisoire

Ces profils permettent de tester Dev 4 sans les services Dev 1–3. Ils ne sont **pas ratifiés** comme contrat inter-projets. Ils ne doivent pas être activés par un producteur réel avant revue API Contracts. L’enveloppe reste celle de `event.schema.json`; choisir explicitement `schema_version: "dev4-local/1.0"` active le payload fermé ci-dessous. L’enveloppe legacy `1.0` reste rétrocompatible.

Tous les identifiants ci-dessous sont des exemples documentaires, jamais chargés en base. Chaque payload rejette les champs inconnus.

| `event_type` | Champs requis dans `payload` | Limite locale |
|---|---|---|
| `WORK_CREATED` | `work_id`, `title` | Décrit un work existant; ne le crée pas dans la base maître. |
| `EVIDENCE_SUBMITTED` | `evidence_id`, `work_id`, `content_sha256` (64 caractères hexadécimaux) | Référence/hash seulement; aucun contenu privé de preuve n’est accepté. |
| `POLICY_DECIDED` | `decision_id`, `decision` (`ALLOW`, `BLOCK`, `HUMAN_REVIEW`), `reason_code`, `policy_version` | Aucun score n’est calculé localement. `ALLOW` reste une décision reçue du producteur authentifié. |
| `SETTLEMENT_UPDATED` | `settlement_id`, `status` (`PENDING`, `SUBMITTED`, `CONFIRMED`, `FAILED`, `REVERSED`) | Observation seulement; aucun transfert ni signature. `transaction_id` est requis pour `SUBMITTED` et `CONFIRMED`; `CONFIRMED` demande aussi une preuve de finalité. |

## Profils de settlement ajoutés en Phase 5

- `SETTLEMENT_REQUESTED` accepte `settlement_id` et crée une observation locale `REQUESTED`. Cela n’émet ni ne signe un ordre.
- `POLICY_DECIDED` accepte facultativement `settlement_id`. Avec cet identifiant, `ALLOW` mène à `AUTHORIZED`, `HUMAN_REVIEW` à `POLICY_PENDING` et `BLOCK` à `POLICY_BLOCKED`. Une décision sans identifiant settlement ne change pas un settlement.
- `SETTLEMENT_UPDATED` et `HEDERA_TRANSACTION_OBSERVED` acceptent `settlement_id`, `status`, `transaction_id` et `network`. `SUBMITTED` exige une référence de transaction. `CONFIRMED` exige en plus `finality_confirmed: true` et `consensus_timestamp` provenant de la source observatrice.
- Les transitions impossibles, une confirmation sans référence/finalité ou un projet incohérent sont bloqués et audités. Une observation n’autorise pas l’agent à soumettre ou signer une transaction.
- Le poller autonome utilise un port d’observation. Sans adaptateur configuré il consigne `UNAVAILABLE`, conserve l’état courant et ne fabrique aucune confirmation.

Exemple documentaire :

```json
{
  "schema_version": "dev4-local/1.0",
  "producer_id": "local-contract-test",
  "event_id": "example-work-001",
  "event_type": "WORK_CREATED",
  "project_id": "EXAMPLE-PROJECT",
  "occurred_at": "2026-10-03T12:00:00Z",
  "source": "contract-test",
  "payload": {"work_id": "example-work", "title": "Documentary example"}
}
```

Le producteur doit encore s’authentifier avec `X-Producer-ID` et `X-API-Key` lorsque l’authentification d’ingestion est activée. `source` n’est pas une identité. Avant merge d’intégration, remplacer/compléter ces profils avec les schémas approuvés par les propriétaires des données et ajouter leurs tests consumer-provider.
