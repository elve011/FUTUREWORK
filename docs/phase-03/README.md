# Phase 3 — AI Command Center web

## Objectif

Fournir une interface de monitoring Dev 4 utilisable en mode autonome mock, puis connectee aux endpoints Django disponibles. L'interface reprend le theme de la maquette FUTUREWORK : sidebar, fond clair, cartes blanches, accents indigo/violet et vert, responsive desktop/mobile.

## Perimetre livre

- Resume projet : progression, jalons, preuves, risques et compteurs de reglement issus du snapshot API.
- Registre des agents avec statut et derniere activite.
- Journal projet/audit avec recherche globale et filtre de statut; les identifiants d'evenement et de trace restent visibles.
- Alertes actives provenant de l'endpoint du projet.
- Activite Hedera et transactions avec liens HashScan fournis par l'API.
- Monitoring de settlement en lecture seule; aucun bouton ne soumet ou n'approuve un paiement.
- Indicateurs de livraison et provenance separee des sources projet, evenements et Hedera.
- Etats de chargement, API principale indisponible, flux secondaire indisponible, resultat vide et preview locale explicite.
- Navigation par ancres fonctionnelles; recherche globale sur activite, alertes et feed Hedera.
- Proxy Next `/backend-api/*` vers Django configurable par `BACKEND_API_URL`.

## Endpoints consommes

| Vue | Endpoint |
|---|---|
| Snapshot dashboard | `GET /api/projects/FW-DEMO-001/dashboard` |
| Timeline / audit | `GET /api/projects/FW-DEMO-001/activity` |
| Alertes actives | `GET /api/projects/FW-DEMO-001/alerts` |
| Activite Mirror Node | `GET /api/projects/FW-DEMO-001/hedera/activity` |
| Transactions | `GET /api/projects/FW-DEMO-001/hedera/transactions` |

Le snapshot dashboard est requis pour marquer l'API comme connectee. Les feeds secondaires sont charges separement; un echec est signale et ne bascule pas les feeds disponibles en donnees de preview.

## Demarrage local

1. Backend, depuis la racine du depot :

   ```powershell
   python backend/manage.py migrate
   python backend/manage.py runserver 127.0.0.1:8000
   ```

2. Frontend, dans `frontend` :

   ```powershell
   npm install
   npm run dev
   ```

Par defaut, le proxy Next cible `http://127.0.0.1:8000`. Pour une autre adresse, definir `BACKEND_API_URL` cote serveur avant de lancer Next. Pour tester les donnees de preview, arreter Django : le dashboard marque alors explicitement les fixtures comme locales et non live.

## Verification

```powershell
npm run lint
npm run build
```

La validation backend existante reste : `python backend/manage.py test command_center -v 1`.

## Limites connues / passage aux phases suivantes

- L'API backend fournit actuellement des fixtures mock pour le projet et Hedera; la presence d'un lien HashScan ne signifie pas que la transaction a ete observee sur le reseau.
- La page de settlement est en lecture seule. Le cycle d'etats, le polling sans Celery et le gate d'approbation appartiennent aux phases 4 et 5.
- Les historiques de metriques ne sont pas encore echantillonnes; la phase 7 ajoutera les series temporelles.
- Le dashboard cible le projet demonstrateur `FW-DEMO-001`; un selecteur de projets attendra le contrat projet global.
- Les sections Create Project et Wallet sont des liens d'orientation vers les vues projet/monitoring, pas des formulaires de creation ou un portefeuille connecte.
- Les quatre noms d'evenements de demonstration demeurent a confirmer avec le catalogue partage API Contracts.
