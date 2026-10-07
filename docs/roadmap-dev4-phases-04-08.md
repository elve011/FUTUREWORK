# FUTUREWORK Dev 4 — plan restant, phases 4 à 8

Ce document remplace le plan initial des phases 4–8 dans `roadmap-dev4.md`. Il a été établi après inspection du dépôt : Django/DRF, SQLite, modèles d’audit et d’agents, ingestion synchronisée, LangGraph déterministe, fixtures de démonstration et dashboard Next.js déjà présents. La cible demandée est un mini-projet autonome utilisant SQLite uniquement, sans PostgreSQL et sans Celery.

## 1. État réel au départ

| Domaine | Déjà présent | À livrer pour le fonctionnement inter-projets réel |
|---|---|---|
| Événements | Enveloppe JSON, validation DRF, empreinte payload, trace créée par Dev 4, idempotence sur `event_id`, redaction de champs sensibles | Catalogue partagé signé/versionné, identité du producteur, compatibilité backward, validation sémantique et gestion des événements répétés ou hors ordre |
| Persistance | ORM Django, migrations SQLite, `SystemEvent`, `AgentAction`, `AgentDecision`, `AgentExecution`, `AgentAlert`, `AuditLog` | Contraintes et index métier, statut durable de traitement, journal protégé contre modification, rétention, sauvegarde/restauration et limites mono-écrivain testées |
| Orchestration | Workflow LangGraph synchrone avec routage déterministe; Planner, Evidence, Risk et Settlement au registre | Contrat d’exécution commun, vraie responsabilité et preuve par agent, idempotence, délais, reprise, état de santé et interdiction d’inventer des résultats |
| Sources | Adaptateurs projet et Hedera mock; modes séparés | Adaptateurs réels des contrats des Dev 1–3 et Mirror Node Hedera Testnet; provenance par valeur; mode live fail-closed |
| Risque / score | Décision locale conservatrice et fixture de risque | Score autoritatif du propriétaire métier (Dev 3/contrat global), version, date, facteurs et source; « inconnu » quand la donnée est absente |
| Settlement | Une demande est retenue en `HUMAN_REVIEW`; le backend ne signe pas | Cycle d’observation durable et rapprochement avec le résultat réel; aucun transfert ou signature privée dans Dev 4 |
| Interface | Dashboard responsive de base, projet `FW-DEMO-001`, sources explicitement étiquetées | Projet sélectionné depuis l’API, flux réels, détails auditables, filtres, actions autorisées et états de permissions; aucune fixture en mode live |

## 2. Règles de conception non négociables

1. **Une source de vérité par donnée.** Dev 4 affiche et corrèle les événements; il ne remplace pas le propriétaire de Work, Evidence, Policy ou Settlement. Chaque champ agrégé garde `source`, `source_record_id`, `observed_at` et, si disponible, la version du contrat.
2. **Mini-projet autonome, sans données métier générées en live.** Dev 4 doit démarrer et fonctionner avec sa propre API, son dashboard, SQLite et son worker. Sans source externe, il accepte des données réelles saisies/importées avec provenance utilisateur, ou affiche un état vide; il ne fabrique ni projet ni score. Les adaptateurs des autres mini-projets restent optionnels et branchés aux contrats communs. Fixtures réservées aux tests, séparées de tout registre live.
3. **Pas de score fabriqué par Dev 4.** Le score Risk est consommé depuis son propriétaire contractuel. Dev 4 stocke la valeur reçue, son échelle, sa version, ses facteurs explicatifs et son horodatage. En absence de ces éléments : score `UNKNOWN`, pas zéro et pas de décision `ALLOW`.
4. **Pas de transfert initié par l’agent Settlement.** Dev 4 surveille une intention et une transaction soumise par le composant autorisé. Aucun secret de signature ou clé Hedera ne réside dans Django, le navigateur ou les logs Dev 4.
5. **Livraison d’événements au moins une fois, traitement idempotent.** Ne pas supposer un transport exactly-once. Un doublon ne produit ni deuxième action métier ni deuxième règlement. Une collision d’identité est rejetée et auditée.
6. **Temps UTC, montants exacts.** Les dates entrantes conservent `occurred_at`; Dev 4 ajoute `received_at` et `processed_at`. Montants en unités mineures entières ou `Decimal` selon le contrat; jamais `float` pour une somme financière.
7. **Données manquantes distinctes de zéro.** API et UI préservent `null`/`UNKNOWN`, horodatage et source; aucune interpolation de valeur pour remplir le dashboard.
8. **Compatibilité explicite.** Les endpoints déjà utilisés restent compatibles ou sont versionnés. Les noms des quatre événements locaux (`WORK_CREATED`, `EVIDENCE_VERIFIED`, `POLICY_DECIDED`, `SETTLEMENT_UPDATED`) ne deviennent pas des contrats d’équipe tant que les responsables API Contracts ne les ont pas confirmés.

9. **SQLite à charge déclarée.** Déployer un seul nœud Dev 4 (API/web et un worker de fond) sur la même machine. SQLite sérialise les écritures; garder les transactions courtes, le volume d’écriture modeste, traiter proprement `database is locked`, mesurer les verrous et ne jamais lancer plusieurs pollers. Ne pas utiliser un fichier DB sur un partage réseau.

## Phase 4 — Socle autonome, registre local et ingestion fiable

Cette phase se termine sans dépendance aux autres mini-projets. Les profils `dev4-local/1.0` sont le contrat de test interne de Dev 4; leur approbation comme contrats inter-projets appartient à la phase d’intégration finale.

### 4.1 Registre local et données

- Démarrer sur une base neuve avec un registre vide, sans seed de projet de démonstration.
- Créer un projet manuellement ou importer un CSV/JSON fourni par un propriétaire de données.
- Conserver provenance `MANUAL`/`IMPORTED`, acteur, date, source record et empreinte du fichier.
- Faire l’import en deux étapes : aperçu avec rejets par ligne, puis commit authentifié et atomique.
- Ne pas traiter les exemples ni les placeholders comme des projets réels. Des projets réels ne sont ajoutés qu’à partir d’informations fournies et vérifiables.
- Utiliser les profils d’événements locaux versionnés pour les tests autonomes; ne pas attendre ni simuler les API de Dev 1–3.

### 4.2 Ingestion et worker SQLite

- Valider enveloppe, version locale, taille, horodatage, champs et payload avant acceptation.
- Écrire l’événement, l’audit et l’outbox dans une transaction courte; produire une trace corrélée et redacter les secrets avant persistance.
- Dédupliquer les répétitions identiques et rejeter une collision d’identifiant.
- Traiter les événements avec la commande Django `process_events`, un worker séquentiel supervisé, des baux de reprise, retries bornés et quarantaine; aucun Celery ni PostgreSQL.
- Afficher les états `pending`, `processing`, `retry`, `processed` et `quarantined` dans l’API et le dashboard.

### 4.3 Vérification d’exploitation locale

- Tester le démarrage depuis une base SQLite fraîche, le registre vide, la création et l’aperçu/commit d’import.
- Tester le worker après redémarrage, les doublons, collisions, erreurs et reprise après panne.
- Créer une sauvegarde SQLite cohérente et effectuer une restauration vers un nouveau chemin; contrôler intégrité, migrations, projets, audits et événements.
- Mesurer le délai d’ingestion jusqu’à la visibilité d’une alerte sur l’environnement local et noter le résultat, sans le présenter comme une mesure de production.
- Documenter commandes, configuration, limites SQLite et procédure d’import des données réelles.

### Sortie de phase 4 autonome

- API, dashboard et worker démarrent seuls avec SQLite; une base neuve affiche un registre vide.
- Création et import contrôlés fonctionnent avec provenance et audit; l’aperçu ne publie aucune ligne.
- Les tests d’ingestion, idempotence, redaction, reprise, quarantaine, sauvegarde et restauration passent.
- Le template JSON ne contient aucun projet importable avant saisie de données valides.
- Les profils `dev4-local/1.0` sont documentés et testés; aucun accord des autres développeurs n’est requis à ce stade.

### À conserver pour la phase d’intégration

La validation des contrats communs, des identités inter-services, des payloads propriétaires, du score Risk officiel, des API externes et de Hedera Testnet est reportée à l’intégration. Jusque-là, ces sources sont absentes ou `UNAVAILABLE`; les résultats ne sont jamais fabriqués.
## Phase 5 — Quatre agents métier, exécution durable et observation du settlement

Le périmètre de cette phase est autonome : contrats d’agent locaux versionnés, événements `dev4-local/1.0`, registre SQLite et adaptateur de settlement explicitement indisponible en l’absence de source. Les API réelles et l’approbation des contrats partagés restent dans la phase d’intégration.

### 5.1 Contrat commun d’agent

Définir un protocole versionné commun aux quatre agents : `agent_key`, version, événement/commande source, données autorisées, préconditions, sortie typée, statut (`SUCCEEDED`, `BLOCKED`, `RETRYABLE_FAILURE`, `PERMANENT_FAILURE`), raisons codées, durée, références sources, `trace_id`/`span_id` et clé d’idempotence. Les agents ne lisent pas directement les tables des autres mini-projets; ils passent par API/adaptateurs explicitement autorisés.

| Agent | Responsabilité réelle Dev 4 | Entrées et limites | Sorties/audit attendus |
|---|---|---|---|
| **Planner** | Construire une projection de progression et de dépendances depuis le contrat Project/Work; signaler milestone bloqué ou en retard à partir d’échéances fournies par le propriétaire. | Ne crée ni ne replanifie des engagements; ne déduit pas une échéance inexistante; ne transforme pas un payload incomplet en progrès. | Projection avec IDs amont, version/horodatage source, règles de calcul versionnées, éléments manquants et alertes reliées. |
| **Evidence** | Vérifier présence, format, empreinte/signature ou référence de preuve selon la règle convenue avec le propriétaire Evidence. | Ne déclare pas vraie une preuve seulement parce qu’un hash existe; ne copie pas de contenu privé; ne change pas l’état maître d’une preuve. | Verdict `VERIFIED`/`REJECTED`/`UNKNOWN`, règle et version, hashes/références non sensibles, raison codée et trace. |
| **Risk & Policy** | Consommer le score et la décision du moteur propriétaire (Dev 3 ou contrat partagé), vérifier leur provenance et appliquer le policy gate de Dev 4. | Aucun score synthétique, formule improvisée, score par défaut ou `ALLOW` si la source manque/expire. Toute nouvelle formule doit avoir propriétaire, version, échelle, calibration et validation métier. | Valeur originale, échelle, source, `model_or_policy_version`, timestamp, facteurs autorisés, seuil/règle appliqué, décision et motif. |
| **Settlement Monitor** | Suivre l’ordre déjà autorisé, observer la transaction réellement envoyée par le composant détenteur de la clé, rapprocher son statut via la source officielle. | Read-only pour signature/soumission. Aucun transfert si événement, décision, montant, devise, destinataire ou référence ne concordent. | État et transition historisés, ID de transaction réel, réseau, réponse source, timestamp de consensus quand confirmé, dernier contrôle et alerte si bloqué/échec. |

- Distinguer statut de santé agent (heartbeat réel, dernière erreur, version déployée) de statut de tâche. `IDLE` en base n’est pas preuve de santé live.
- Exécuter le routage métier déterministe; LLM éventuel uniquement pour synthèse non décisionnelle et avec entrée/sortie tracée. Aucun LLM n’autorise un paiement ou ne modifie un score.
- Enregistrer inputs et outputs sous forme de références/empreintes minimisées plutôt que de dupliquer des payloads sensibles.

### 5.2 Settlement lifecycle sans Celery

- Formaliser les états de l’ordre et de la transaction séparément : `REQUESTED → POLICY_PENDING → AUTHORIZED → SUBMITTED_BY_OWNER → OBSERVED_PENDING → CONFIRMED | FAILED | UNKNOWN`. Ne pas sauter une transition; `UNKNOWN` n’est jamais `CONFIRMED`.
- Stocker séparément intention/ordre, décision, référence d’opération, observation transaction et historique append-only de transition. Les statuts `SUBMITTED_BY_OWNER` ou `AUTHORIZED` ne prouvent pas la finalité réseau.
- En autonomie, conserver seulement l’identifiant de transaction rapporté par un événement local; la soumission et la signature restent hors de Dev 4. Le branchement au propriétaire externe appartient à l’intégration.
- Ajouter `monitor_settlements --once` et worker récurrent sans Celery : sélection batch bornée, lease expirante, checkpoints, retry/backoff, arrêt propre, métriques de lag et interdiction de traiter deux fois le même ordre.
- Configurer le poller comme processus supervisé (systemd/Container orchestrator/Task Scheduler selon déploiement); ne pas lancer le poller dans chaque processus web Django.
- Définir fenêtres de confirmation, transaction absente, transaction remplacée/dupliquée, erreur Mirror Node et expiration avec le contrat Hedera et propriétaire métier. Ces durées viennent de la politique; elles ne sont pas codées comme vérité universelle.
- Générer l’alerte via transition idempotente et outbox, sans exiger que la page dashboard reste ouverte.

### Sortie de phase 5

- Les quatre agents ont des contrats `dev4-agent/1.0`, résultats typés, références source et scénarios locaux; aucun accès Dev 1–3 n’est requis.
- Un seul worker est autorisé; redémarrages, replays et requêtes web simultanées ne créent pas de doubles actions/transitions grâce aux contraintes d’unicité et aux mises à jour conditionnelles. Aucun `select_for_update` SQLite n’est supposé.
- Test local complet : ordre demandé → décision locale explicitement attribuée → soumission rapportée → observation d’adaptateur de test → statut final uniquement avec preuve de finalité. Source absente ou erreur reste inchangée/`UNKNOWN` et ne devient jamais `CONFIRMED`.
- Aucun chemin Dev 4 ne détient ou n’appelle une clé de signature.

## Phase 6 — Policy, score, approbation humaine et sécurité des actions

- Confirmer le propriétaire du score de risque et son contrat : ID du modèle/règle, version, échelle, `score`, date de calcul, facteurs justifiables, expiration et statut de confiance. Si ces champs ne sont pas fournis, afficher « score inconnu » et appliquer la règle fail-closed approuvée.
- Documenter la règle de décision comme policy versionnée : seuils et conditions, états `ALLOW`, `BLOCK`, `HUMAN_REVIEW`, `PENDING`, données obligatoires, durée de validité et comportement sur score périmé. Les seuils sont approuvés par le product/risk owner, pas choisis par Dev 4 seul.
- Ajouter un endpoint d’approbation/rejet authentifié, protégé par rôles, autorisation par projet, validation CSRF/JWT adaptée au mode, et séparation approbateur/acteur si exigée. Aucun rôle ne se déduit d’un champ envoyé par le navigateur.
- Une approbation signe logiquement la décision métier (identité d’authentification résolue côté serveur, date serveur, policy version, motif, objet exact et idempotency key); elle n’autorise pas une modification ultérieure du montant ou du destinataire.
- Utiliser contrôle de concurrence/version (`If-Match` ou version DB), expiration des demandes et protection contre double clic/rejeu. Retourner conflit si la ressource ou la policy a changé depuis l’écran d’approbation.
- Refuser par défaut une donnée manquante, une transaction d’un autre réseau/projet, un montant/devise/destinataire qui diffère, une décision expirée ou une signature source invalide; aucune confirmation optimiste.
- Séparer les permissions lecture, acquittement d’alerte, approbation métier et configuration source; masquer côté UI ne remplace jamais le contrôle backend.
- Écrire un `AuditLog` append-only pour chaque consultation/action sensible, policy et approbation; stocker `actor_id` venant du fournisseur d’identité, `request_id`, adresse/service d’origine selon politique, raison, avant/après expurgés et références.
- Gérer secrets via gestionnaire de secrets du déploiement; rotation, révocation et scopes minimaux. Ne jamais intégrer secrets Mirror Node, JWT ou clés Hedera à `NEXT_PUBLIC_*`.
- Définir contrôles d’accès par projet et tests IDOR sur tous les endpoints, y compris `/history`, `/alerts`, `/metrics` et liens de transaction.

### Sortie de phase 6

- Politique approuvée et versionnée avec propriétaire; cas score absent/expiré/illégal couverts.
- Approbation impossible sans identité authentifiée et autorisation sur le projet; replay/concurrence ne crée pas deux décisions.
- Les journaux démontrent qui a décidé quoi, quand, selon quelle version, sans révéler de secret.

## Phase 7 — Sources live, vérité des événements et observabilité Hedera

### 7.1 Adaptateurs des mini-projets

- Implémenter un adaptateur par frontière réelle, avec port domaine stable et DTO normalisé : Project/Work, Evidence, Risk/Policy, Settlement. Configurer base URL, version, identité service et timeout côté serveur.
- Lire l’OpenAPI/health des services réels au démarrage ou dans CI; valider les réponses, schémas et versions avant mapping. Une source absente ou incompatible produit `SOURCE_UNAVAILABLE`/`CONTRACT_MISMATCH`, jamais une fixture de remplacement.
- Pour les callbacks entrants : authentifier/signature selon contrat, vérifier replay/time skew, conserver ID de livraison amont, et garder le contrôle idempotent Dev 4.
- Pour les appels sortants : timeout connect/read, limite de taille, retry uniquement pour erreurs transitoires sûres, `Retry-After`, circuit breaker mesuré et correlation ID transmis. Pas de retry automatique sur mutation sans idempotency key reconnue par le producteur.
- Définir cache par type de donnée et TTL autorisé; le score Risk et la décision ne sont pas servis stale au-delà de leur validité métier.

### 7.2 Adaptateur Hedera Testnet

- Cible de lancement : Testnet, configuration explicitement nommée et liens HashScan dérivés du réseau réellement configuré. Mainnet reste bloqué jusqu’à une revue sécurité/produit dédiée.
- Implémenter lecture Mirror Node pour HCS topics/messages, HTS tokens/transfers, contrats/logs et scheduled transactions pertinents. Mapper les champs amont dans un DTO versionné sans perdre l’ID original, le network, la source et le consensus timestamp.
- Traiter la pagination à l’aide du lien de continuation retourné (`links.next`); respecter limites, fenêtres temporelles et filtres documentés. Borne de pages et de durée par requête; ne pas construire des offsets arbitraires et ne jamais supposer que l’endpoint renvoie toute l’histoire.
- Contrôler codes HTTP, réponses partielles, timestamps, statut de transaction, type de transaction et absence d’entité. `404`/non trouvé ou timeout ne vaut pas échec confirmé.
- Confirmer un settlement uniquement sur le signal et la règle de finalité convenus avec le propriétaire Hedera; stocker le statut de consensus rapporté et l’identifiant retourné. Une URL HashScan est une référence de navigation, pas une preuve suffisante à elle seule.
- Ajouter timeout, backoff avec jitter, quota/concurrence de requêtes configurable, cache read-only, checkpoint de polling et alerte de retard de source. Vérifier à la livraison le quota/conditions du fournisseur et l’OpenAPI du réseau ciblé.
- Ne pas publier d’identifiant ou d’URL de fixture en mode Testnet live; les captures de preuve live doivent mentionner réseau et horodatage de consultation.

### Sortie de phase 7

- Les sources Project, Evidence, Risk, Settlement et Hedera sont configurables séparément; dashboard expose pour chacune `mode`, `status`, `last_success_at`, `last_error_code` et fraîcheur.
- Testnet renvoie uniquement des résultats observés sur ce réseau; mode live impossible à confondre avec mock.
- Timeout, `429`, `5xx`, pagination, donnée incomplète, ID inconnu et réponses de statut contradictoires couverts.

## Phase 8 — Dashboard opérationnel, alertes, métriques et livraison intégrée

### 8.1 Contrat UI/API et interactions de l’opérateur

- Remplacer le projet fixé dans le composant par le projet autorisé renvoyé par l’API (sélecteur seulement si l’identité a plusieurs projets accessibles); conserver la maquette FUTUREWORK et rendre tous les panneaux responsives.
- Cartes des **quatre** agents avec vraie santé, dernière exécution, version, capacité, dernière erreur et lien d’historique; distinguer santé du worker, statut d’exécution et statut de décision.
- Recherche/filtres serveur paginés : project, événement, agent, trace/correlation ID, gravité, statut, intervalle UTC et type Hedera. Synchroniser filtres dans l’URL pour partage/rechargement; boutons reset et export contrôlé si permis.
- Vue détail événement/trace : enveloppe redacted, chaîne des spans parent/enfant, agent exécuté, version, décision, action, alertes et référence transaction; ne jamais afficher secrets ni données auxquelles l’utilisateur n’a pas accès.
- Vue Alerts : tri par gravité/ancienneté, état active/resolved, provenance, trace, acquittement autorisé et commentaire. L’acquittement n’efface ni ne résout automatiquement le problème source.
- Vue settlement : états séparés, dernière observation, source/réseau, compte à rebours de policy et erreur; actions approve/reject uniquement si endpoint autorisé, rôle valide et gate actif. Aucune action de wallet/signature.
- Vue Hedera/Explorer : topic/token/contract/scheduled transaction/transaction, filtres et détail; liens HashScan externes validés contre le réseau et IDs fournis.
- Exposer erreurs par source, fraîcheur, retard de polling et mode live/testnet. États loading, empty, forbidden, stale, partial failure et unavailable séparés; ne pas substituer une valeur de fixture.
- Notifications in-app dédupliquées à partir d’alertes réelles, compteur non lu, lecture et acquittement authentifiés. Ajouter SSE/WebSocket seulement si le backend et l’hébergement en garantissent l’exploitation; sinon polling avec fréquence documentée et ETag/cursor.
- Accessibilité clavier, labels, focus visible, couleurs non seules porteuses d’état, tableaux navigables, réduction animation; tester au moins mobile étroit, tablette et desktop.

### 8.2 Mécanique des alertes et scoring des indicateurs

- Implémenter une règle d’alerte par événement/signal contractuel : retard selon deadline du projet, preuve manquante selon checklist du propriétaire, score Risk officiel, échec réel de transaction, heartbeat d’agent périmé, source Hedera dégradée.
- Exiger `source_event_id`, `rule_id/version`, première occurrence, dernière occurrence, gravité, état, `trace_id`, projet, lien d’origine et clé de déduplication. Répétition met à jour une alerte existante au lieu d’inonder la liste.
- Mesurer le critère « alerte affichée <10 s » de bout en bout : source timestamp → ingestion → persistance → API/UI visible. Instrumenter p50/p95/p99 et expliquer les cas où l’indisponibilité amont empêche le SLA; le backend ne peut garantir délai d’un fournisseur externe.
- Construire les KPI uniquement avec des records réels et formules versionnées : progression depuis unités contractuelles, délais depuis dates officielles, score depuis Dev 3, settlement depuis les transitions observées. Afficher numérateur, dénominateur, source, intervalle et fraîcheur.
- Échantillonner métriques depuis les flux réellement persistés avec clé stable et fenêtre définie; idempotence du collecteur et séparation UTC. Pas de seed aléatoire ni de courbe historique synthétique dans la vue live.
- Retenir `null/UNKNOWN` quand source/calcul manque; préciser les éventuels retards d’indexation Hedera avant de calculer un délai.

### 8.3 Validation, exploitation et démonstration

- Tests de contrat à trois niveaux : schémas producteurs figés, tests consumer-provider avec chaque mini-projet, et test API Dev 4/OpenAPI. Versionner les fixtures de contrat; ne pas confondre celles-ci avec la base de démo réelle.
- Tests backend : unités/règles des quatre agents, migrations SQLite, transaction courte, idempotence sur écritures simultanées, erreur `database is locked`, outbox, reprise worker, transition interdite, audit, contrôle d’accès, fuite de secret et calcul de score.
- Tests intégration : services de staging des équipes, Hedera Testnet, pages de résultats, retries, `429`, timeout, API partielle, horloge UTC, retards et conflit de décision.
- Tests frontend : rendu au clavier/mobile, vraie réponse API, chaque statut réseau/source, permissions, pagination, filtre/URL et erreur sans données de secours live. Ajouter un scénario browser end-to-end du parcours accepté et du parcours bloqué.
- Observabilité serveur : logs JSON structurés, request/trace/correlation IDs, latence/status par adaptateur, profondeur backlog, âge du plus vieux message, erreurs par code, alertes doublonnées, exécutions par statut et poller heartbeat. Pas de payload ou credential brut dans logs.
- Définir SLO/SLA mesurables avec l’équipe (fraîcheur source, délai d’alerte, disponibilité dashboard), seuils d’alerte on-call et runbooks « provider down », « backlog monte », « DB indisponible », « mauvais mapping ».
- Déployer migrations SQLite puis API/worker/web sur une même machine et un disque durable; configurer health/readiness distincts, arrêt drainé du worker, rollback de release, sauvegarde et restauration testées.
- Vérifier qu’un `FW_MODE=live` avec source absente échoue clairement. Le mini-projet autonome démarre sans les services Dev 1–3 et accepte des événements réels authentifiés ou des données réelles saisies/importées; à défaut de données, il montre un état vide, jamais une fausse preview dans le registre live.
- Produire runbook, diagramme de flux, dictionnaire des données, catalogue d’événements, matrice agent→événement→contrat, variables/secrets, politique de rétention, limites connues et script de démonstration.

### Sortie finale de phase 8

- Un même parcours réel est traçable : événement d’un mini-projet → validation/version → audit/outbox → agent(s) autorisés → résultat réel de policy/score → settlement observé → alerte/KPI → dashboard selon les droits de l’utilisateur.
- Les quatre sources d’agents sont expliquées et testées; aucun score ou statut métier n’est inventé, et chaque champ live affiche source/fraîcheur.
- Aucune transaction n’est soumise ou signée par Dev 4; toute décision critique est authentifiée et auditée.
- Tests SQLite, contrat entre projets, backend, frontend et browser e2e passent; runbook de reprise et rollback validé. La capacité concurrente maximale mesurée et le seuil d’alerte de verrouillage sont documentés.
- Un échec amont laisse un état explicite `UNKNOWN/UNAVAILABLE/STALE`, génère l’alerte adaptée et ne devient jamais un `ALLOW`, un score `0` ou un faux `CONFIRMED`.

## Ordre de travail conseillé pour un sprint de 8 jours

Cette séquence livre d’abord le mini-projet autonome. Les contrats et accès staging des Dev 1–3 débloquent ensuite les adaptateurs, mais ne conditionnent ni le démarrage ni le fonctionnement de base. Si les contrats manquent, les panneaux intégrés affichent `UNAVAILABLE`; ne pas fabriquer de données pour respecter le calendrier.

| Jour | Résultat démontrable |
|---|---|
| 1 | Valider le contrat local Dev 4, le registre vide, les regles de saisie, les evenements de test et les criteres d acceptation autonomes. |
| 2 | SQLite durable, migrations, validation événement, utilisateur local/producteur authentifié; tests idempotence et verrouillage. |
| 3 | Outbox/worker Django sans Celery, audit corrélé, statut durable, redaction; ingestion d’un vrai événement saisi/importé ou fourni par une API accessible. |
| 4 | Contrat et exécution des quatre agents; comportement `UNKNOWN`/erreur; premières vues d’historique réel. |
| 5 | Settlement monitoring/poller, transitions et idempotence; raccordement transaction au service qui signe, sans clé dans Dev 4. |
| 6 | Policy/score officiel, validation humaine authentifiée, permissions et tests de refus/rejeu. |
| 7 | Adaptateurs Testnet/mini-projets, pagination et freshness; dashboard responsive branché sur les vraies sources et filtres/détails. |
| 8 | Tests de bout en bout, panne et reprise, mesure SLA alertes, OpenAPI/docs/runbook, répétition de démo staging et corrections bloquantes. |

Un sprint de 8 jours peut livrer un MVP autonome en staging. L’intégration inter-projets et Testnet dépend des contrats et accès disponibles, mais n’est pas une condition de démarrage du mini-projet. Cette cible ne prouve pas une capacité à forte concurrence; tester puis publier la limite de charge SQLite. La mise en production, la certification du score et l’audit de sécurité externe restent des gates distinctes.

## Decisions avant integration inter-projets

1. Catalogue officiel et version des événements; identité producteur, auth, politique de retries et propriétaire du contrat API.
2. Machine d’hébergement, chemin du fichier SQLite sur disque local durable, sauvegarde/restauration, rétention et identité des services.
3. Source de score Risk, échelle/version/validité, propriétaire d’approbation et seuils policy autorisés.
4. Propriétaire qui construit/signe/soumet un settlement, schéma exact montant/devise/destinataire et règle de finalité attendue.
5. Réseau Hedera Testnet, endpoints officiels accessibles, limites/quota au moment du déploiement, identifiants d’entités autorisés et URL HashScan correcte.
6. Utilisateurs/roles de la démo, droits de lecture/approbation par projet, fournisseur d’identité et responsabilité de revue de sécurité.

## Références techniques à revérifier au déploiement

- SQLite n’autorise qu’un écrivain à la fois; WAL permet lecteurs et écrivain de coexister mais ne crée pas plusieurs écrivains et ne convient pas à un filesystem réseau : [SQLite — WAL](https://www.sqlite.org/wal.html). Django expose des commandes de gestion adaptées aux traitements autonomes et à l’exécution planifiée : [Django — Custom management commands](https://docs.djangoproject.com/en/5.2/howto/custom-management-commands/).
- Vérifier endpoints, filtres, pagination et schémas contre le réseau utilisé, et suivre les liens de page retournés plutôt que supposer le contenu complet : [Hedera Testnet Mirror Node REST API / OpenAPI](https://testnet.mirrornode.hedera.com/api/v1/docs/).
