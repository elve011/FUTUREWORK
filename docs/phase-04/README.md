# Phase 4 â€” contrats, SQLite et ingestion durable

## Objectif et pÃ©rimÃ¨tre

Cette phase sÃ©pare lâ€™acceptation dâ€™un Ã©vÃ©nement de son traitement. Dev 4 reste autonome : Django/DRF + SQLite local, une commande worker sÃ©quentielle, aucun broker, Celery, PostgreSQL ou service Dev 1â€“3 requis au dÃ©marrage. Lâ€™API ne signe ni nâ€™envoie de transaction Hedera.

## Flux livrÃ©

1. `POST /api/events/ingest` valide lâ€™enveloppe fermÃ©e (256 KiB max), lâ€™horodatage et lâ€™Ã©vÃ©nement autorisÃ©. `schema_version` (dÃ©faut `1.0`) et `producer_id` sont optionnels pour prÃ©server les producteurs legacy; lâ€™API interdit les champs enveloppe inconnus.
2. Lâ€™API calcule SHA-256 sur le payload canonique; elle redige les valeurs dont la clÃ© ressemble Ã  un secret avant persistance.
3. Une transaction SQLite courte Ã©crit `SystemEvent`, lâ€™audit `EVENT_INGESTED` et `EventOutbox`. La rÃ©ponse `202` inclut `event_id`, `trace_id`, `status=RECEIVED`, `processing_status=PENDING` et `received_at`.
4. Un doublon strictement identique retourne `200`, le mÃªme `trace_id` et nâ€™ajoute pas de tÃ¢che. La rÃ©utilisation de `event_id` pour un contenu diffÃ©rent retourne `409 EVENT_ID_CONFLICT`.
5. `process_events` prend un bail singleton SQLite puis traite les Ã©vÃ©nements dus un par un. Lâ€™orchestration et son accusÃ© outbox sont dans la mÃªme transaction; le worker ne fait aucun appel rÃ©seau dans cette transaction.
6. En cas dâ€™erreur, un code normalisÃ© sans texte dâ€™exception est auditÃ©; retry exponentiel bornÃ© (jusquâ€™Ã  5 tentatives par dÃ©faut), puis `QUARANTINED`. Lâ€™expiration du bail permet la reprise aprÃ¨s arrÃªt brutal.

## Registre autonome, saisie et import

- `GET /api/projects` liste uniquement les `ProjectReference` effectivement crÃ©Ã©s/importÃ©s. Une base neuve renvoie `count: 0`, pas le projet `FW-DEMO-001`.
- `POST /api/projects` crÃ©e un seul projet avec provenance `MANUAL`.
- `POST /api/projects/import/preview` accepte `{ "projects": [...] }` en JSON ou un fichier CSV/JSON multipart, 2 MiB et 500 lignes maximum. Il calcule SHA-256, valide chaque ligne, signale les lignes refusÃ©es et crÃ©e un lot `PREVIEW`; il ne rend aucun projet visible.
- `POST /api/projects/imports/{batch_id}/commit` importe atomiquement les lignes acceptÃ©es, marque leur provenance `IMPORTED` et empÃªche les commits rÃ©pÃ©tÃ©s ou par un autre opÃ©rateur.
- Toutes les Ã©critures demandent `X-Operator-ID` et `X-Operator-Key`, vÃ©rifiÃ©es contre `FW_OPERATOR_API_KEYS`. Lâ€™acteur vient du credential configurÃ©, jamais dâ€™un champ dans le fichier. Chaque crÃ©ation/import est dans `ProjectAuditLog`.
- Lâ€™aperÃ§u JSON utilise la forme `{"projects":[{"external_id":"â€¦","title":"â€¦","status":"â€¦","description":"â€¦","source_record_id":"â€¦"}]}`. `external_id` et `title` sont requis; status absent reste `UNKNOWN`. Les doublons du fichier et du registre sont refusÃ©s.
- Le dashboard sÃ©lectionne un projet du registre local, ne rattache aucune fixture dâ€™un autre projet et prÃ©sente ses mÃ©triques comme `null/UNKNOWN` tant quâ€™une source autorisÃ©e ne les fournit pas. Lâ€™Ã©cran sans projet est explicitement vide. Les indicateurs outbox `pending`, `processing`, `retry`, `processed` et `quarantined` sont fournis par lâ€™API et affichÃ©s dans lâ€™activitÃ©.

Configurer une clÃ© opÃ©rateur avant de dÃ©marrer Django (exemple de dÃ©veloppement seulement; remplacer la valeur) :

```powershell
$env:FW_OPERATOR_API_KEYS = "emna:replace-with-a-local-secret"
python manage.py runserver
```

Le formulaire du dashboard demande lâ€™identifiant et la clÃ©; il garde la clÃ© uniquement dans la mÃ©moire de la page. Lâ€™API ne persiste jamais cette clÃ©.

## Profils Ã©vÃ©nementiels isolÃ©s

Pour tester sans Dev 1â€“3, `schema_version: "dev4-local/1.0"` active les profils fermÃ©s et typÃ©s documentÃ©s dans [`dev4-local-events-v1.md`](../api-contracts/dev4-local-events-v1.md). Ils couvrent WORK, EVIDENCE, POLICY et SETTLEMENT, sans contenu privÃ© de preuve, score calculÃ© localement ni transfert. Ils restent provisoires et ne remplacent pas les contrats approuvÃ©s. Le schÃ©ma historique `1.0` reste acceptÃ© pour les producteurs legacy.

## Contrat et identitÃ© du producteur

Le schÃ©ma partagÃ© se trouve dans [`event.schema.json`](../api-contracts/event.schema.json). Les champs historiques restent valides; les mÃ©tadonnÃ©es facultatives versionnent progressivement lâ€™enveloppe. Les noms dâ€™Ã©vÃ©nements locaux restent Ã  ratifier avec les responsables API Contracts/Dev 1â€“3 avant publication comme contrat commun.

En dÃ©veloppement, lâ€™ingestion peut fonctionner sans secret. Pour lâ€™environnement de dÃ©ploiement, configurer `FW_INGEST_AUTH_REQUIRED=true` et `FW_INGEST_API_KEYS` au moyen du gestionnaire de secrets de lâ€™hÃ´te, au format `producer-id:secret`. Lâ€™appel doit fournir `X-Producer-ID` et `X-API-Key`; si le corps contient `producer_id`, il doit correspondre. `source` ne constitue jamais une preuve dâ€™identitÃ©. En lâ€™absence de clÃ©s en mode protÃ©gÃ©, lâ€™API Ã©choue fermÃ© en `503`.

Variables opÃ©rationnelles : `FW_DATABASE_PATH` (chemin absolu vers le disque local durable), `FW_SQLITE_TIMEOUT_SECONDS` (dÃ©faut 5), `FW_INGEST_AUTH_REQUIRED`, `FW_INGEST_API_KEYS`, `FW_MODE_PROJECT`, `FW_MODE_EVENTS`, `FW_MODE_HEDERA`, `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`. Les sources par dÃ©faut sont `mock` en dÃ©veloppement et `live` quand `DJANGO_DEBUG=false`; lâ€™adaptateur live absent Ã©choue clairement au lieu de substituer des fixtures. En dÃ©veloppement, les fixtures existantes sont toujours des dÃ©monstrations explicitement Ã©tiquetÃ©es et non des donnÃ©es de production. SQLite utilise WAL pour un fichier local et `busy_timeout` bornÃ©. Ne pas poser la base sur un partage rÃ©seau ni dÃ©marrer plusieurs workers.

## DÃ©veloppement et exÃ©cution (PowerShell)

Depuis `backend/` :

```powershell
python manage.py migrate
python manage.py runserver
```

Dans un second terminal, lancer exactement un worker supervisÃ© :

```powershell
python manage.py process_events
```

Pour un passage ponctuel (CI, tÃ¢che planifiÃ©e) :

```powershell
python manage.py process_events --once
```

Les rÃ©ponses dâ€™ingestion sont maintenant asynchrones : consulter lâ€™Ã©tat `processing_status`/`status`, lâ€™activitÃ© du projet et lâ€™audit aprÃ¨s le dÃ©marrage du worker. Une rÃ©ponse HTTP `202` signifie Â« durablement reÃ§u Â», pas Â« agent terminÃ© Â».

## Sauvegarde et restauration

CrÃ©er un instantanÃ© cohÃ©rent (SQLite Online Backup API, intÃ©gritÃ© contrÃ´lÃ©e avant publication atomique) :

```powershell
python manage.py backup_sqlite C:\data\backups\dev4.sqlite3
```

Pour restaurer, arrÃªter API et worker, conserver une copie de la base actuelle, remplacer le fichier de base par la sauvegarde vÃ©rifiÃ©e, puis redÃ©marrer et vÃ©rifier `/healthz`, les migrations et les traces. Ne pas copier uniquement le fichier `.sqlite3` pendant que WAL Ã©crit. Les permissions/chiffrement au repos et la rÃ©tention de sauvegarde dÃ©pendent de lâ€™hÃ´te de dÃ©ploiement et doivent y Ãªtre dÃ©finis.

Pour valider la restauration sans toucher Ã  la base live, restaurer vers un nouveau chemin; la commande refuse explicitement dâ€™Ã©craser la base configurÃ©e ou un fichier existant :

```powershell
python manage.py restore_sqlite C:\data\backups\dev4.sqlite3 C:\data\restore-test\dev4-restored.sqlite3
```

Le modÃ¨le JSON Ã  remplir avec des enregistrements fournis par le propriÃ©taire et le guide dâ€™aperÃ§u/commit sont dans [`projects-import.template.json`](projects-import.template.json) et [`real-project-import.md`](real-project-import.md). Ces fichiers ne crÃ©ent ni ne seedent de projets automatiquement.

## VÃ©rification reproductible

Depuis `backend/` :

```powershell
python manage.py makemigrations --check --dry-run
python manage.py check
python manage.py test command_center --verbosity 2
```

Depuis la racine du dÃ©pÃ´t, les vÃ©rifications du contrat v1 :

```powershell
python -m unittest discover -s tests/phase-01 -p "test_*stdlib.py"
python -m pytest tests/phase-01/test_event_schema.py
```

Les tests backend couvrent la rÃ©ception asynchrone, le doublon/collision, champs inconnus, taille maximale, redaction, source/producteur, auth fail-closed, profils Ã©vÃ©nementiels provisoires, routage, alertes, retry/quarantaine, bail/Ã©vÃ©nement aprÃ¨s redÃ©marrage, projet vide, saisie authentifiÃ©e, import CSV/JSON en deux Ã©tapes, provenance/audit, file visible dans le dashboard et backup/restauration vers un nouveau fichier vÃ©rifiÃ©e par `integrity_check`.

## Critères de sortie et éléments restant à vérifier

- **Implémenté et couvert par les tests :** migrations SQLite, événement/audit/outbox atomiques, worker sans Celery, reprise, retries/quarantaine, redaction, registre local, création/import CSV/JSON avec aperçu puis commit, provenance/audit, dashboard vide/sélecteur, sauvegarde/restauration.
- **À vérifier en exploitation locale :** effectuer une restauration réelle vers une nouvelle base de test, puis noter intégrité et contenu restauré; mesurer le délai entre réception et visibilité d’une alerte.
- **Données réelles à fournir :** enregistrer les projets de l’équipe à partir de leurs identifiants et descriptions source. Aucun projet n’est injecté automatiquement; le modèle JSON reste volontairement invalide tant que ses champs requis sont vides.
- **Intégration ultérieure :** approbation des contrats inter-projets, clés des producteurs externes, score officiel Risk et adaptateurs Dev 1–3/Hedera. Ces éléments ne bloquent pas le mini-projet autonome.
La garantie de livraison est *at least once*; lâ€™objectif applicatif est un effet idempotent. Une panne aprÃ¨s la rÃ©ception conserve lâ€™Ã©vÃ©nement en outbox. Les erreurs permanentes restent visibles en quarantaine et ne sont pas marquÃ©es comme succÃ¨s.


