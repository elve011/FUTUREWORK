# FUTUREWORK Dev 4 — état et plan de livraison

Ce document suit la section 22 du cahier des charges. « Fait » signifie implémenté et vérifié dans ce dépôt; « partiel » signifie qu'une première tranche existe mais que le critère complet n'est pas atteint.

## État vérifié du dépôt

Branche actuelle : `developer-4`. Le dépôt contenait initialement seulement son README. La branche contient maintenant un backend Django/DRF autonome, des migrations, des adaptateurs mock, le dashboard API, une orchestration LangGraph et une première page Next.js reprenant le thème fourni.

### Exigences FR-A

| ID | État | Éléments vérifiés / reste à faire |
|---|---|---|
| FR-A-01 Registre agents | **Partiel** | API enregistre Planner, Evidence, Risk, Settlement et renvoie leur statut; page dashboard affiche les quatre. Statut opérationnel réel et historique temps réel restent à relier. |
| FR-A-02 Orchestrateur LangGraph | **Partiel** | Workflow compilé route les quatre événements de démo locaux et conserve action/décision. Les noms restent à confirmer dans le catalogue API Contracts partagé; les événements système restants doivent aussi être intégrés aux contrats réels. |
| FR-A-03 AgentAction / AgentDecision | **Partiel** | Modèles, persistance, filtres agent/projet, endpoint historique disponibles. Le panneau UI d'audit complet avec recherche par trace/projet et détails de spans reste à construire. |
| FR-A-04 Dashboard agrégé | **Livré — phase 3 UI** | Dashboard Next.js connecté au snapshot et aux flux activité, alertes, transactions et Hedera. Recherche, filtre, provenance par source, navigation, états loading/erreur/vide et preview locale explicite livrés. Adaptateurs live et métriques historiques restent en phases 6–7. |
| FR-A-05 Mirror Node | **Partiel** | Fixtures mock HCS, HTS, contrat, scheduled transaction et HashScan links, plus interfaces/adaptateur mock. Adaptateur live testnet, pagination, timeout et rapprochement transaction restent à faire. |
| FR-A-06 Alertes < 10 s | **Partiel** | Les six événements d'alerte déclenchent une `AgentAlert` dans l'ingestion synchrone; test automatisé mesure le lot sous 10 s. La création isolée par chaque événement, l'horodatage de délai, les vues/notifications et le traitement des événements venant du Mirror Node restent à valider. |
| FR-A-07 Settlement monitoring | **Non terminé** | Événement routé vers l'agent settlement et requête de release mise en `HUMAN_REVIEW`; pas encore de cycle de vie `checkRelease`, `prepareSettlement`, polling, timeout, confirmation/failure. |
| FR-A-08 Policy | **Partiel** | Décisions enregistrées; action settlement critique conservée en `HUMAN_REVIEW` en absence d'approbation. Il manque la décision humaine/API d'approbation, le lien décision↔transaction et la preuve durable du gate avant action. |
| FR-A-09 Blockchain Explorer | **Partiel** | Les fixtures et quelques liens HashScan apparaissent sur le dashboard. Écran filtrable transactions/tokens/topics/contrats et détails d'objet manquants. |
| FR-A-10 Notifications in-app | **Non terminé** | Modèle `Notification` créé; aucune création/lecture/marquage comme lu ni UI. |
| FR-A-11 Métriques historiques | **Partiel** | Modèle et endpoint métriques existent; pas de processus d'échantillonnage, série mock historique ni graphique journalier. |
| FR-A-12 Bascule mock/live par source | **Partiel** | Paramètres séparés project/events/Hedera; les sources mock fonctionnent et un mode live sans adaptateur renvoie une indisponibilité explicite. Les adaptateurs live et leur configuration/état de santé ne sont pas implémentés. |

### Ce qui passe actuellement

- Backend : `python backend/manage.py test command_center -v 2` — **25 tests réussis**.
- Contrat JSON : `python -m pytest tests/phase-01 -q` — **17 tests réussis**.
- Migrations : `python backend/manage.py makemigrations --check --dry-run` — aucune migration manquante.
- Frontend : `npm run build` — build réussi avant les toutes dernières retouches du layout/proxy; à relancer.
- Frontend lint : `npm run lint` — zéro erreur, un avertissement d'import inutilisé a été corrigé; à relancer.
- `git diff --check` — propre au dernier contrôle backend. À relancer après fin du frontend.

## Phases restantes et étapes

La phase 3 UI est livrée. Le plan détaillé faisant autorité pour tout le travail restant (phases 4 à 8) est [`roadmap-dev4-phases-04-08.md`](roadmap-dev4-phases-04-08.md); il remplace les premières notes de phase conservées plus bas dans cette page. Une phase ne sera acquise que lorsque ses critères de sortie et preuves passent.

### Phase 0 — Cadrage cahier des charges — terminée

1. Extraire le périmètre Dev 4 de la section 22.
2. Construire la matrice FR-A-01…12, les scénarios et l'enveloppe d'événement.
3. Marquer les noms des quatre événements comme exemples locaux jusqu'à confirmation de l'API Contracts globale.

### Phase 1 — Fondation API et persistance — terminée

1. Créer Django/DRF, SQLite et migrations ORM.
2. Ajouter les modèles Agent, Task, Execution, Action, Decision, Alert, Event, AuditLog, Notification et Metric.
3. Construire registre quatre agents, santé API et ingestion idempotente.
4. Générer trace/span et inscrire l'audit initial; retirer les valeurs de type secret des payloads persistés.
5. Documenter l'installation et les commandes.

**Sortie :** migrations propres, événement accepté/rejeté conformément au schéma, événement répété idempotent.

### Phase 2 — Orchestration et scénarios mock — fondation livrée

1. Confirmer la taxonomie d'événements avec les développeurs 1–3 / API Contracts.
2. Compléter le mapping LangGraph de tous les événements contractuels; conserver le routeur métier sans LLM.
3. Créer AgentExecution, AgentAction, AgentDecision et entrées AuditLog à chaque transition.
4. Ajouter fixtures projet, événements et Mirror Node avec provenance mock explicite.
5. Déclencher les six alertes depuis les événements et tester chacune individuellement sous 10 secondes.

**Sortie :** les quatre événements contractuels routent vers le bon agent; toutes les traces relient ingestion, agent, décision et alerte.

### Phase 3 — AI Command Center web — livrée (interface)

1. Terminer le layout App Router, métadonnées, styles et proxy Next `/backend-api/*` vers Django.
2. Connecter le dashboard au endpoint agrégé et afficher la provenance séparée pour chaque source.
3. Compléter les pages/sections Agent Registry, Activity/Audit Timeline, Alerts, Settlement Monitoring et Hedera Activity.
4. Implémenter loading, empty, API error, mode preview mock, recherche et liens de navigation fonctionnels.
5. Vérifier le thème de la maquette sur large écran et mobile; aucun compteur preview ne doit être étiqueté live.

**Sortie :** build/lint propres; dashboard lit l'API quand backend lancé et affiche le preview étiqueté quand il est absent.

### Phase 4 — Settlement Monitoring Agent sans Celery

1. Définir les transitions autorisées `PENDING → CONFIRMED | FAILED | UNKNOWN` et conserver chaque transition.
2. Implémenter `checkRelease`, `prepareSettlement`, `monitorTransaction`, `monitorHedera`, `detectFailure`, `confirmSettlement` derrière ports/adaptateurs.
3. Écrire adaptateur settlement mock avec fixtures pending, success, failure, timeout et non trouvé.
4. Ajouter une commande Django `monitor_settlements --once` et une boucle périodique paramétrable; gérer erreurs/retry sans poll dans les vues HTTP.
5. Ajouter tests d'idempotence, transitions, seuil délai et absence de fausse confirmation.

**Sortie :** démonstration complète pending, confirmed et failed; aucun Celery; API web reste disponible pendant le polling.

### Phase 5 — Policy gate et validation humaine

1. Confirmer avec Dev 3 le schéma de décision, l'identité du décideur, les raisons, la version policy et les preuves obligatoires.
2. Refuser toute action critique sans décision conforme; distinguer `ALLOW`, `BLOCK`, `HUMAN_REVIEW`, `PENDING`.
3. Ajouter endpoint d'approbation/rejet humain authentifié; garder l'action en attente tant que la décision n'est pas persistée.
4. Corréler décision, approbateur, settlement, trace et horodatage dans AuditLog.
5. Tester décision manquante, invalide, répétée, expirée et conflit de policy.

**Sortie :** aucune action critique ne passe hors policy; chaque approbation est traçable.

### Phase 6 — Mirror Node live et modes par source

1. Fixer réseau testnet, base URL officielle Mirror Node, identifiants, critères de confirmation et formats HashScan.
2. Implémenter l'adaptateur live isolé du domaine, avec timeout, pagination, retry/backoff et validation de réponse.
3. Lire HCS, HTS, contrats et scheduled transactions; normaliser leur sortie vers le contrat du dashboard.
4. Rendre le mode projet/événement/Hedera indépendant, observable et testable; empêcher tout mock d'être présenté comme live.
5. Ajouter tests HTTP simulés et une vérification manuelle testnet; secrets uniquement dans variables serveur.

**Sortie :** mode live testnet affiche transactions et HashScan; erreur réseau crée alerte et ne confirme rien.

### Phase 7 — Explorer, alertes, notifications et métriques complètes

1. Construire Explorer filtrable par type, statut, période, topic, token, contrat et transaction.
2. Ajouter page détail objet Hedera et liens HashScan validés selon réseau.
3. Créer notifications in-app pour alertes critiques, endpoints lecture/acquittement et état non lu.
4. Échantillonner `DashboardMetric` à fréquence définie et exposer séries journalières.
5. Ajouter graphiques et filtres aux sections Analytics; vérifier responsive/accessibilité.

**Sortie :** fonctions `Should/Could` du cahier terminées sans dégrader les Must.

### Phase 8 — Intégration, sécurité et démo finale

1. Faire tourner Dev 4 seul de zéro avec SQLite fraîche et fixtures.
2. Exécuter la suite mock complète et vérifier le contrat OpenAPI contre les routes réelles.
3. Tester données mal formées, répétitions, timeouts, permissions, redaction des secrets et transitions concurrentes.
4. Vérifier tous les endpoints/API avec Dev 1–3 sans rendre ces services nécessaires à la démo autonome.
5. Écrire README d'installation, variables, catalogue d'événements, limites, script de démonstration et captures du dashboard.
6. Répéter la démo `event → trace → agent → policy → settlement → Mirror Node → alert/dashboard`.

**Sortie finale :** tous les `Must` passent, les événements sont confirmés avec leurs propriétaires, démo autonome réalisable, documentation/OpenAPI à jour.

## Ordre d'exécution immédiat

1. Terminer et re-vérifier le proxy API/layout du frontend déjà commencé.
2. Construire la vraie UI branchée sur les endpoints dashboard/activity/alerts/Hedera.
3. Finir le cycle settlement mock et sa commande de polling sans Celery.
4. Fermer les décisions ouvertes avec Dev 3 et API Contracts.
5. Ajouter la policy humaine, puis le Mirror Node live.
6. Terminer Explorer, notifications, métriques et scénario de démo.
