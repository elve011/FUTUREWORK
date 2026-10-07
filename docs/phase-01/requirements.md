# Matrice des exigences — cahier des charges, section 22 (Dev 4)

Cette matrice reprend les IDs, priorités et critères de la section fournie. Les tests d'intégration de ces exigences seront ajoutés avec les endpoints et composants correspondants.

| ID | Priorité | Exigence / interprétation de réalisation | Preuve d'acceptation prévue |
|---|---|---|---|
| FR-A-01 | Must | Registre des quatre agents Planner, Evidence, Risk, Settlement, avec statut et dernière activité. | Endpoint registre/statut et cartes Agent Status affichent les quatre entrées. |
| FR-A-02 | Must | Orchestrateur LangGraph route les événements vers les agents et journalise événement, agent choisi et décision. | Quatre événements mock routés correctement et présents dans l'audit. |
| FR-A-03 | Must | Conserver AgentAction et AgentDecision; historique filtrable par agent et projet. | API actions/historique et filtres vérifiés. |
| FR-A-04 | Must | Dashboard agrège progression, unités, milestones, preuves, risques et settlements depuis les mocks, puis sources live. | Agrégat comparé aux fixtures connues et affiché correctement. |
| FR-A-05 | Must | Observer Mirror Node pour HCS, HTS, contrats, Scheduled Transactions; transactions avec liens HashScan. | Fixtures déterministes en mode mock; lecture testnet et lien HashScan en mode live. |
| FR-A-06 | Must | Alertes pour milestone retardé, preuve manquante, risque élevé, transaction échouée, agent bloqué et erreur Hedera. Délai d'affichage inférieur à 10 secondes après événement. | Six fixtures déclenchent chacune une alerte visible dans le délai contractuel. |
| FR-A-07 | Must | Settlement Monitoring suit une transaction jusqu'à confirmation ou échec. | Scénarios pending, confirm et fail; transition et trace conservées. |
| FR-A-08 | Must | Toute action critique passe par une policy `ALLOW`, `BLOCK` ou validation humaine. | Action critique bloquée sans ALLOW; `HUMAN_REVIEW` attend une décision humaine auditée. |
| FR-A-09 | Should | Blockchain Explorer expose transactions, tokens, topics et contrats avec liens HashScan. | Chaque objet fixture navigable vers son lien HashScan correspondant. |
| FR-A-10 | Could | Notifications in-app pour chaque alerte critique. | Création et visibilité d'une notification liée à l'alerte critique. |
| FR-A-11 | Could | Métriques historiques avec courbes d'activité par jour. | Série journalière issue de métriques horodatées. |
| FR-A-12 | Must | Bascule mock/live par source de données. | Configuration indépendante et provenance affichée pour chaque source. |

## Périmètre UI du AI Command Center

- **Global Project Status** : progression, unités terminées/total, milestones terminés/total, preuves, risques, settlements.
- **Agent Status** : Planner, Evidence, Risk, Settlement, statut et dernière activité.
- **Agent Activity** : flux horodaté des actions des agents.
- **Alerts** : alertes actives triées par sévérité.
- **Hedera Activity** : événements HCS, transactions HTS, appels de contrat, Scheduled Tx et événements Mirror Node.
- **Blockchain Explorer** : vue des objets Hedera et liens HashScan.

## Modèles attendus

Le cahier cite `Agent`, `AgentAction`, `AgentTask`, `AgentDecision`, `AgentAlert`, `AgentExecution`, `SystemEvent`, `Notification` et `DashboardMetric`. Leur schéma détaillé appartient à la phase backend, mais les contrats de phase 1 doivent préserver au minimum l'identifiant, le statut, les horodatages, le projet et les identifiants de corrélation nécessaires aux vues ci-dessus.

## API exposée par le cahier

| Méthode | Endpoint | Usage |
|---|---|---|
| GET | `/api/agents` | Registre des agents |
| GET | `/api/agents/status` | Statut des agents |
| GET | `/api/agents/actions` | Actions filtrables |
| GET | `/api/agents/:id/history` | Historique d'un agent |
| GET | `/api/projects/:id/activity` | Flux d'activité du projet |
| GET | `/api/projects/:id/alerts` | Alertes du projet |
| GET | `/api/projects/:id/metrics` | Métriques du projet |
| GET | `/api/projects/:id/hedera/activity` | Activité Hedera |
| GET | `/api/projects/:id/hedera/transactions` | Transactions Hedera |
| GET | `/api/projects/:id/dashboard` | Agrégat du Command Center |
| POST | `/api/events/ingest` | Ingestion de l'enveloppe standard |

Ne pas renommer ces routes pendant l'implémentation sans accord explicite sur le contrat d'API commun.

## Démonstration autonome obligatoire

Le démarrage et la démo du mini-projet Dev 4 ne nécessitent aucun service Dev 1, 2 ou 3. Le projet doit fournir :

1. Projet fixture `FW-DEMO-001`; le visuel fourni montre notamment 64/100 unités et 3/5 milestones. Utiliser ces chiffres dans la fixture de démonstration seulement si le cahier global/API Contracts ne les remplace pas.
2. Générateur ou catalogue d'événements mock des preuves et décisions nécessaires.
3. Fixtures de réponses Mirror Node couvrant HCS, HTS, contrats et Scheduled Transactions.
4. Quatre types d'événements routés par LangGraph (noms exacts à prendre dans le catalogue API global; ne pas figer les noms d'exemple dans un contrat d'équipe).
5. Six fixtures d'alerte permettant de déclencher chacune des catégories FR-A-06.
6. Script de démo sans dépendance aux autres mini-projets.

## Priorité si délai contraint

Respecter les niveaux du cahier: toutes les exigences `Must` avant `Should`, puis `Could`. Les métriques historiques et notifications peuvent donc venir après le registre, l'orchestrateur, l'audit, l'agrégat dashboard, le monitoring, les alertes, le settlement, la policy et les modes mock/live.
