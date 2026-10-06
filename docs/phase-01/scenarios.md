# Phase 1 — Scénarios d'acceptation Dev 4

Les tests d'acceptation du contrat sont décrits dans `tests/phase-01/`. Les scénarios métier ci-dessous traduisent les IDs FR-A du cahier des charges et guideront les tests backend et la démonstration autonome.

| ID | Situation | Résultat attendu |
|---|---|---|
| S01 | Événement nominal valide | Accepté; `trace_id` créé; événement et entrée d'audit persistés; réponse corrélable. |
| S02 | Champ requis absent ou mauvais type | Rejet de validation; erreur structurée; aucune exécution métier ni settlement créé. |
| S03 | Même `event_id` renvoyé | Pas de seconde exécution/settlement; réponse idempotente renvoyant la trace existante. |
| S04 | Agent ciblé indisponible | Exécution `FAILED` ou mise en attente selon contrat; raison auditée; alerte créée. |
| S05 | Policy retourne `BLOCK` | Aucune action de settlement; décision et raison conservées; alerte visible. |
| S06 | Policy retourne `ALLOW` mais transaction absente | Settlement reste `PENDING` ou `UNKNOWN`; aucune fausse confirmation. |
| S07 | Mirror Node rapporte la transaction confirmée | Statut `CONFIRMED` seulement si l'état/champs requis par le contrat sont présents; consensus timestamp et référence enregistrés. |
| S08 | Mirror Node rapporte un échec | Statut `FAILED`; transition historisée; alerte rattachée à la trace. |
| S09 | Mirror Node indisponible ou timeout | Données précédentes conservées; statut non confirmé; erreur de connectivité auditée et alertée; polling peut retenter. |
| S10 | Payload contient une chaîne ressemblant à un secret | Aucun secret/token/clé n'est recopié dans les logs ou messages d'erreur. |
| S11 | Mode mock | Source explicitement marquée `mock`; résultats déterministes; aucun appel réseau Hedera. |
| S12 | Mode live | L'adaptateur live est sélectionné; mêmes contrats et gestion des erreurs que le mock. |
| S13 | Démo autonome `FW-DEMO-001` | Démarre sans les services Dev 1/2/3 et présente toutes les sections obligatoires du Command Center. |
| S14 | Les quatre types d'événement mock documentés sont reçus | LangGraph route chacun vers l'agent attendu; agent, décision et résultat sont consultables. |
| S15 | Chacune des six catégories FR-A-06 est injectée | L'alerte correspondante est affichée dans les 10 secondes suivant l'événement. |
| S15a | Milestone en retard | Alerte `MILESTONE_DELAYED` affichée en moins de 10 s. |
| S15b | Preuve obligatoire manquante | Alerte `EVIDENCE_MISSING` affichée en moins de 10 s. |
| S15c | Risque déclaré élevé par Dev 3 | Alerte `HIGH_RISK` affichée en moins de 10 s; Dev 4 n'invente pas le score de risque. |
| S15d | Transaction Hedera échouée | Alerte `TRANSACTION_FAILED` liée au settlement et à sa trace en moins de 10 s. |
| S15e | Agent bloqué ou indisponible | Alerte `AGENT_BLOCKED` en moins de 10 s avec agent/source identifiés. |
| S15f | Erreur Mirror Node/Hedera | Alerte `HEDERA_ERROR` en moins de 10 s; état de transaction non confirmé. |
| S16 | Policy exige une validation humaine | L'action critique reste suspendue jusqu'à décision humaine; identité, date et décision sont auditées. |
| S17 | Agrégat dashboard comparé au jeu fixture | Progression, unités, milestones, preuves, risques et settlements correspondent exactement aux données mock. |
| S18 | Modes mock/live configurés par source | Changer la source Hedera ne change pas la source projet; provenance de chaque métrique/donnée est affichée. |
| S19 | Objets Hedera du type HCS, HTS, contrat et Scheduled Tx | Affichés dans l'activité/Explorer avec identifiant de type et lien HashScan si disponible. |

## Exemple de timeline attendue

```text
event received (event_id)
  → trace created (trace_id)
  → agent selected (agent_id)
  → policy decision (ALLOW/BLOCK + reason)
  → settlement observed (PENDING/CONFIRMED/FAILED/UNKNOWN)
  → alert emitted if needed
```

Chaque entrée garde son horodatage UTC, `trace_id`, `span_id`, type d'événement, statut et source. `transaction_id`, `consensus_timestamp` et URL HashScan sont optionnels tant qu'ils ne sont pas connus.

## Scénario démo autonome

1. Démarrer uniquement Dev 4 en `FW_MODE=mock`.
2. Charger le projet fixture `FW-DEMO-001` et vérifier l'agrégat global.
3. Injecter les quatre événements mock prévus par le catalogue d'événements.
4. Vérifier le routage vers Planner, Evidence, Risk et Settlement et leur historique.
5. Déclencher les six catégories d'alerte; chronométrer la visibilité (<10 s).
6. Afficher l'activité Hedera depuis les fixtures HCS/HTS/contrat/Scheduled Tx, ainsi que les références HashScan de démonstration identifiées comme mock.
7. Montrer un settlement pending puis confirmé et un settlement échoué, avec timeline et audit.
