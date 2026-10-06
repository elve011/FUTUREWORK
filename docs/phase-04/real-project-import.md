# Phase 4 — Importer des projets réels dans le registre local

Le registre de Dev 4 ne reçoit que les projets transmis et validés par un opérateur. Le fichier `projects-import.template.json` est un modèle vide de sens métier : ses identifiants `REPLACE_...` doivent être remplacés par des valeurs issues de la source réelle de l’équipe. Ne pas importer ce fichier avant remplacement et vérification.

## Données requises

Pour chaque projet réel, fournir :

- `external_id` : identifiant stable du projet dans sa source;
- `title` : nom exact du projet;
- `status` : statut réel connu, ou `UNKNOWN` si non confirmé;
- `description` : description autorisée pour le dashboard;
- `source_record_id` : identifiant de l’enregistrement source si disponible.

Ne pas inventer de projet ou d’identifiant. L’import conserve `IMPORTED`, l’acteur, la date, le hash du fichier et les erreurs ligne par ligne.

## Préparer le fichier

1. Copier `projects-import.template.json` vers un nouveau fichier, par exemple `projects-real.json`.
2. Remplacer les deux enregistrements de modèle par les projets fournis par le propriétaire des données. Ajouter ou retirer des objets selon le nombre réel de projets.
3. Vérifier qu’aucun `external_id` n’est vide ou dupliqué et que les titres correspondent à la source.
4. Ne pas inclure de clés, jetons, données privées de preuves ou secrets.

Format accepté :

```json
{
  "projects": [
    {
      "external_id": "ID_REEL_SOURCE",
      "title": "Nom réel du projet",
      "status": "IN_PROGRESS",
      "description": "Description approuvée",
      "source_record_id": "ID_SOURCE"
    }
  ]
}
```

## Lancer le backend

Depuis `backend/`, configurer une clé d’opérateur locale et démarrer Django :

```powershell
$env:FW_OPERATOR_API_KEYS = "emna:REMPLACER_PAR_UN_SECRET_LOCAL"
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Dans un autre terminal PowerShell, depuis la racine du dépôt, définir les mêmes identifiants opérateur. Utiliser `curl.exe` explicitement pour éviter l’alias PowerShell :

```powershell
$operatorId = "emna"
$operatorKey = "REMPLACER_PAR_LE_MEME_SECRET_LOCAL"
curl.exe -X POST "http://127.0.0.1:8000/api/projects/import/preview" -H "X-Operator-ID: $operatorId" -H "X-Operator-Key: $operatorKey" -F "file=@docs/phase-04/projects-real.json;type=application/json"
```

## Vérifier puis valider l’import

1. Lire la réponse d’aperçu : `accepted`, `rejected`, `batch_id`, le rapport de lignes et `commit_url`.
2. Corriger le fichier si un projet est refusé, puis créer un nouvel aperçu. L’aperçu seul ne modifie pas le registre.
3. Vérifier auprès du propriétaire que les projets acceptés et leurs identifiants sont exacts.
4. Appeler le `commit_url` retourné, en gardant les mêmes en-têtes opérateur :

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/projects/imports/REMPLACER_PAR_BATCH_ID/commit" -H "X-Operator-ID: $operatorId" -H "X-Operator-Key: $operatorKey" -H "Content-Type: application/json" -d "{}"
```

5. Vérifier `GET /api/projects`, le dashboard du projet et l’audit d’import. Le commit est atomique, attribué à l’opérateur et ne peut pas être rejoué.

## Données réalistes et données réelles

Une description plausible ou un exemple JSON n’est pas une donnée réelle. Tant que les propriétaires ne fournissent pas les enregistrements et leurs identifiants sources, le registre doit rester vide. Le fichier template n’est pas une fixture et n’est pas chargé automatiquement.
