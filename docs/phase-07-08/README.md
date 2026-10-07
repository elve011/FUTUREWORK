# Dev 4 — Phases 7 et 8

## Périmètre livré

### Phase 7 — projets et engagements

- Chaque projet créé par l’interface possède un propriétaire; les membres actifs sont enregistrés séparément avec le rôle `FREELANCER` ou `CLIENT`.
- L’accord persiste le budget facultatif, la devise, les heures, les Work Units, les dates, le dépôt déclaré et les conditions. L’accord et le jalon restent `PENDING` / `PROPOSED` tant qu’un humain ne les approuve pas.
- Les milestones, preuves, approbations, audits et sources sont persistés. Les comptes membres peuvent lire leur projet; le propriétaire seul peut modifier son titre/description ou gérer les membres.
- Les métriques viennent du registre. Les données absentes restent `UNKNOWN` (`null` API); une déclaration d’achèvement manuelle n’est jamais qualifiée de preuve vérifiée.
- Sources distinguées : `MANUAL`, `IMPORTED`, `GITHUB_API`, `HEDERA_MIRROR_NODE`, `TEST_ONLY`. Le fixture de l’interface porte `TEST_ONLY` et `DEMO_ONLY`.

### Phase 8 — événements et orchestration

- Contrat local versionné `dev4-local/2.0`: `event_id`, projet, type, horodatage avec fuseau, source, producteur, corrélation et payload. Les producteurs historiques `1.0` restent acceptés; une version inconnue est rejetée.
- Création d’un accord complet → événement Planner en outbox. Le worker local produit une proposition déterministe à cinq jalons, sans approbation automatique.
- Soumission d’une preuve `TEST_ONLY` → Evidence calcule verdict explicable et hash local. Dépôt lié au projet → le fixture est refusé; GitHub réel exige le dépôt allowlisté et la configuration serveur. Aucun token n’est envoyé ou affiché par le navigateur.
- La collecte GitHub est en lecture seule. Le `github_login` du profil reste une déclaration utilisateur tant que l’OAuth GitHub n’est pas intégré; même si toutes les vérifications techniques réussissent, Evidence garde le verdict `UNKNOWN` avec `GITHUB_IDENTITY_NOT_OAUTH_VERIFIED`. Il ne faut donc pas prendre une identité GitHub déclarée pour une preuve d’identité.
- Risk exige des événements du même projet/correlation, le jalon du Planner, l’exécution Evidence, l’achèvement déclaré, l’approbation client explicite, les conditions et le niveau de risque. Absence → `HUMAN_REVIEW`; risque/preuve bloquante → `BLOCK`.
- `ALLOW` porte toujours le scope `LOCAL_SIMULATION_NO_TRANSFER`. Dev 4 ne signe ni n’envoie une transaction; le suivi Hedera reste `not-configured` jusqu’à l’intégration Mirror Node.
- Les événements sont idempotents par `event_id`; les décisions, sources, versions et traces existent déjà dans l’audit AgentAction/AgentDecision/AgentExecution et les lignes de domaine.

## Démarrer sous PowerShell

Ouvre trois terminaux dans `C:\Users\Pc\Desktop\hackathon`.

**Terminal 1 — migrations et API Django**

```powershell
cd C:\Users\Pc\Desktop\hackathon\backend
python manage.py migrate
python manage.py runserver
```

**Terminal 2 — worker durable**

```powershell
cd C:\Users\Pc\Desktop\hackathon\backend
python manage.py process_events
```

Laisse ce terminal ouvert. Il affiche les événements traités. Pour une seule passe contrôlée, utilise `python manage.py process_events --once`.

Quand Dev 4 reçoit les dépôts autorisés et un token serveur, configure dans l’environnement Django `FW_GITHUB_ALLOWED_REPOSITORIES=organisation/depot` et `FW_GITHUB_TOKEN=...`. Ne place jamais ce token dans Next.js, le profil, les requêtes du navigateur ou Git. L’UI envoie seulement les SHA de commits et numéros de PR.

**Terminal 3 — frontend Next.js**

```powershell
cd C:\Users\Pc\Desktop\hackathon\frontend
npm run dev
```

Ouvre `http://localhost:3000/signup`. Pour générer des identifiants de démonstration (mot de passe affiché une seule fois dans le terminal), arrête d’abord le serveur Django puis lance dans le backend:

```powershell
python manage.py seed_demo_freelancers
```

Le seeder crée des comptes marqués `DEMO_ONLY`, dont `client.demo@example.test` avec rôle `CLIENT`. Ne réutilise pas ces comptes en production.

## Scénario UI complet

1. Inscris-toi sur `/signup` avec un compte freelancer, ou connecte-toi avec un compte de démonstration.
2. Dans « Créer un projet », saisis un ID unique, un titre, `100` heures, `100` Work Units, une deadline après la date de début et au moins une condition. Laisse GitHub vide pour le test synthétique. Le formulaire crée l’accord et l’événement Planner.
3. Attends que le worker traite l’événement. La carte Workflow doit afficher cinq jalons `PROPOSED`, la provenance et `PENDING` pour l’approbation de l’accord. La progression reste inconnue tant qu’aucun achèvement n’est persisté.
4. Choisis le fixture `SUCCESS`, clique « Soumettre preuve TEST_ONLY », puis attends le worker. Une preuve `VERIFIED`, score local `100`, hash et références locales doivent apparaître. Ce score n’est pas celui officiel de Dev 2.
5. Clique « Déclarer terminé » sur le premier jalon, puis « Évaluer le risque ». Sans approbation client, le résultat doit être `HUMAN_REVIEW` avec `REQUIRED_POLICY_FACT_UNKNOWN`.
6. Depuis le compte propriétaire, ajoute `client.demo@example.test` comme membre `CLIENT`. Déconnecte-toi, connecte ce compte, ouvre le même projet et clique « Approuver » sur le même jalon.
7. Reconnecte le freelancer et clique « Évaluer le risque » à nouveau. Avec preuve vérifiée, achèvement déclaré, approbation client, conditions et risque bas, la décision attendue est `ALLOW`, scope `LOCAL_SIMULATION_NO_TRANSFER`.
8. Refais une preuve avec CI `FAILURE`. Elle doit être `REJECTED` avec motif `CI_FAILED`; l’évaluation Risk correspondante bloque ou demande revue. Rien ne doit apparaître comme transaction Hedera confirmée.
9. Connecte-toi avec un deuxième freelancer : le projet du premier compte ne doit pas apparaître et son URL doit répondre 404. Un membre autorisé peut lire, mais seul le propriétaire peut modifier le projet.

## Vérifications

```powershell
cd C:\Users\Pc\Desktop\hackathon\backend
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test command_center
```

```powershell
cd C:\Users\Pc\Desktop\hackathon\frontend
npm run lint
npm run build
```

Tests couvrant le contrat v2 et ses versions, création/validation/date, données inconnues, membres et isolation, propositions Planner persistées, evidence `TEST_ONLY` vérifiée/rejetée, corrélation Risk, décision `HUMAN_REVIEW`, approbation client et `ALLOW` strictement local.
