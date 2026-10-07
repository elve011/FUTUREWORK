# Phase 5 — Agents versionnés et observation durable du settlement

## Objectif et périmètre autonome

Chaque événement local accepté produit une exécution d’agent versionnée, un résultat typé et une référence source persistés dans SQLite. Le mini-projet utilise uniquement les contrats locaux Dev 4. Aucun service Dev 1–3, PostgreSQL, Celery, compte Hedera ou clé de signature n’est nécessaire au démarrage.

Les résultats incomplets restent `UNKNOWN`, `PENDING` ou `BLOCKED`. Les agents ne construisent pas un score officiel, ne prouvent pas la vérité d’une preuve depuis son hash, ne créent pas de work dans une base maître et ne signent ni ne soumettent un règlement.

## Contrat commun d’exécution

Chaque `AgentExecution` conserve :

- `agent`, `agent_version` (`dev4-agent/1.0`) et statut d’exécution;
- événement source, `trace_id`, `span_id`, clé idempotente par agent/événement;
- hash canonique de l’entrée, références source minimisées, code de raison;
- résultat JSON typé et horodatages de début/fin.

Les statuts possibles sont `QUEUED`, `RUNNING`, `COMPLETED`, `BLOCKED`, `RETRYABLE_FAILURE` et `PERMANENT_FAILURE`. L’unicité `(agent, event)` interdit une seconde exécution du même couple. Le worker existant rejoue les événements en échec via l’outbox et conserve son backoff/quarantaine.

| Agent | Résultat autonome | Garde-fou |
|---|---|---|
| Planner | Projection des identifiants work, titre, échéance source et données inconnues | Aucun progrès ni deadline calculé si absent. |
| Evidence | Référence, hash reçu et verdict `UNKNOWN`, `SOURCE_REPORTED_VERIFIED` ou `REJECTED` selon l’événement source | Un hash reçu ne signifie pas preuve vérifiée. |
| Risk & Policy | Décision versionnée fournie par l’événement; `score` et source de score restent `null` | `HIGH_RISK` sans décision autoritative mène à `HUMAN_REVIEW`. |
| Settlement Monitor | État d’ordre, transaction/réseau observés, transitions, essais de polling | Lecture seule; aucune signature ou soumission. |

La disponibilité du worker est exposée à part du statut de tâche : heartbeat récent donne `health_status=AVAILABLE`, heartbeat absent donne `UNKNOWN`, heartbeat trop ancien donne `STALE`. L’exécution d’un événement ne prouve pas seule que le worker est toujours disponible.

## Cycle d’état du settlement

Transitions gérées :

```text
REQUESTED -> POLICY_PENDING -> AUTHORIZED -> SUBMITTED_BY_OWNER
                                      -> OBSERVED_PENDING -> CONFIRMED | FAILED | UNKNOWN
REQUESTED/POLICY_PENDING -> POLICY_BLOCKED
```

Le passage vers `SUBMITTED_BY_OWNER` est possible uniquement après `AUTHORIZED`. `CONFIRMED` exige un identifiant de transaction, `finality_confirmed=true` et le timestamp de consensus retourné par l’observateur. Les états terminaux ne sont pas réouverts. Chaque transition pointe vers son événement source et garde source, transaction et horodatage. Les failures/policy blocks génèrent une alerte idempotente.

Le poller `monitor_settlements` appelle un port lecture seule hors transaction DB, enregistre les essais, puis place toute nouvelle observation validée dans l’outbox générale. Le worker `process_events` applique ensuite la transition. Si la source est absente, le poller écrit `UNAVAILABLE` sans changer le statut de settlement.

## API ajoutée

| Route | Usage |
|---|---|
| `GET /api/settlements?project_id=&status=&limit=&offset=` | Liste paginée et filtrable des observations locales. |
| `GET /api/settlements/{settlement_id}` | Détail avec historique append-only des transitions et dernières tentatives du poller. |
| `GET /api/agents/{id}/history` | Résultats d’exécution, version, code de raison, références, hash d’entrée et sortie typée. |

Le contrat local de settlement est décrit dans [`../api-contracts/dev4-local-events-v1.md`](../api-contracts/dev4-local-events-v1.md). Ces profils ne sont pas des contrats d’équipe ratifiés.

## Worker de monitoring

Depuis `backend/`, lancer un passage ponctuel :

```powershell
python manage.py monitor_settlements --once
```

Worker supervisé :

```powershell
python manage.py monitor_settlements --poll-interval 5 --batch-size 50 --lease-seconds 30
```

Lancer un seul monitor et un seul worker `process_events`. En mode autonome, `FW_MODE_SETTLEMENT=local` utilise une source indisponible explicite; il n’invente pas de résultat. Un futur adaptateur live se branche derrière `command_center.adapters.settlement`, en phase d’intégration.

## Tests requis

Les contrats d’agents détaillés et la configuration GitHub read-only sont documentés dans [`agent-workflows.md`](agent-workflows.md). Cette documentation précise les règles locales versionnées ajoutées après le premier socle Phase 5, ainsi que leurs limites avant intégration avec Dev 1–3.

```powershell
python manage.py makemigrations --check --dry-run
python manage.py check
python manage.py test command_center --verbosity 2
```

Couverture spécifique :

- sortie/version/idempotence Planner; hash seul Evidence → `UNKNOWN`; absence de score Risk;
- heartbeat absent/récent et séparation health/exécution;
- ordre settlement `REQUESTED → POLICY → SUBMITTED → OBSERVED → CONFIRMED`;
- submission avant authorization, confirmation sans preuve de finalité, transaction sans ordre et réutilisation hors projet bloquées;
- history/API paginée, transitions uniques et alertes de failure;
- source de monitoring absente sans fausse confirmation, source test contrôlée qui place une observation dans l’outbox, confirmation source invalide rejetée.

## Limites restantes avant intégration

- Aucun adaptateur réel de settlement/Hedera n’est livré dans cette phase; le poller reste `UNAVAILABLE` hors tests du port.
- L’autorité, l’authentification des producteurs, la fenêtre de finalité et la preuve canonique de consensus seront alignées avec les propriétaires de données dans la phase d’intégration.
- Le score officiel Risk reste inconnu en autonomie. Les décisions observées sont conservées avec la source/version reçues; elles ne sont pas recalculées localement.
