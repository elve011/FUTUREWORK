# Phase 6 — Comptes freelancers et authentification

## Périmètre livré

- Authentification Django par session, avec middleware de session, CSRF et cookies `HttpOnly`/`SameSite=Lax`.
- En développement, les origines frontend `localhost:3000` et `127.0.0.1:3000` sont autorisées pour le flux CSRF via le rewrite Next.js. En production, configurer explicitement `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Inscription `FREELANCER`, connexion, déconnexion et endpoint d'identité.
- Profil `FreelancerProfile` : rôle, nom affiché, statut, identifiant GitHub public et préférences.
- Rôles enregistrés : `FREELANCER`, `CLIENT` et `ADMIN`. L'inscription publique ne permet pas de choisir son rôle.
- Projets rattachés à un propriétaire. Les routes freelancer listent/créent les projets du compte courant et renvoient 404 pour un projet d'un autre compte.
- Les routes opérateur historiques restent accessibles uniquement avec les en-têtes opérateur configurés.
- Commande de comptes de démonstration disponible uniquement avec `DEBUG=True`. Elle crée des utilisateurs `DEMO_ONLY`, génère des mots de passe aléatoires et les affiche une seule fois.
- Le profil n'accepte qu'un identifiant GitHub ; aucun token GitHub ou secret Hedera n'est stocké ou rendu par l'API.
- Pages frontend `/login` et `/signup`. La racine vérifie la session, charge le registre privé freelancer et propose la création d'un projet.

## Routes

| Méthode | Route | Usage |
|---|---|---|
| `GET` | `/api/auth/csrf` | Initialise le cookie CSRF et renvoie le token à utiliser dans `X-CSRFToken`. |
| `POST` | `/api/auth/signup` | Crée un compte freelancer et ouvre sa session. |
| `POST` | `/api/auth/login` | Ouvre une session existante. |
| `POST` | `/api/auth/logout` | Ferme la session (CSRF requis). |
| `GET` | `/api/auth/me` | Renvoie l'identité publique de la session. |
| `GET`, `POST` | `/api/freelancer/projects` | Liste/crée les projets appartenant au compte connecté. |
| `GET` | `/api/freelancer/projects/{project_id}` | Renvoie un projet uniquement à son propriétaire. |

L'interface appelle les routes via le rewrite Next.js `/backend-api/*`, donc le cookie de session reste same-origin.

## Comptes de démonstration

Depuis `backend/` :

```powershell
python manage.py seed_demo_freelancers
```

La commande ajoute `emna.freelancer@example.test`, `sami.freelancer@example.test` et `nour.freelancer@example.test`. Les mots de passe ne sont pas constants : ils sont générés aléatoirement et affichés uniquement lors de la création. La commande refuse `DEBUG=False` et ne convertit jamais un compte existant non-demo en compte de démonstration.

Le flag `DEMO_ONLY` identifie ces profils. Ne pas recopier leurs mots de passe dans un fichier de configuration ou un environnement de production.

## Démarrage et validation

```powershell
cd C:\Users\Pc\Desktop\hackathon\backend
python manage.py migrate
python manage.py runserver
```

Dans un autre terminal :

```powershell
cd C:\Users\Pc\Desktop\hackathon\frontend
npm run dev
```

Ouvrir `http://localhost:3000/signup` pour créer un compte freelancer, puis créer un projet depuis le dashboard. Le compte ne voit que ses propres projets.

Tests backend :

```powershell
cd C:\Users\Pc\Desktop\hackathon\backend
python manage.py test command_center.test_phase6_auth --verbosity 2
python manage.py test command_center --verbosity 2
python manage.py check
python manage.py makemigrations --check --dry-run
```

Les comptes d'essai, projets et scénarios synthétiques ne constituent pas une preuve GitHub réelle ni une observation Hedera réelle.
