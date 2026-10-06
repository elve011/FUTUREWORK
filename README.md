# FUTUREWORK

## Démonstration de paiement Hedera testnet

Le dépôt contient un compte `DEMO_ONLY` avec un projet démo relié au dépôt GitHub public `elve011/repo-test`, trois milestones terminés (100/100 unités), des preuves et approbations `TEST_ONLY` synthétiques. Le backend peut lire commits, PR, reviews et CI depuis GitHub en mode `FW_MODE_EVIDENCE=github`. Le login `elve011` du compte démo est une déclaration de profil, pas une liaison OAuth : les faits sont lus mais la source ne peut pas confirmer l’identité du contributeur. Les fixtures préchargées ne sont pas des preuves réelles importées de GitHub. La démo autorise, après confirmation explicite dans le navigateur, un transfert **réel de 0,1 HBAR testnet par milestone** vers le compte destinataire configuré. Ce flux n’est pas une simulation, mais les HBAR testnet n’ont pas de valeur mainnet.

### 1. Préparer les données locales

Ouvre un terminal PowerShell dans VS Code (`Ctrl`+`Shift`+`` ` ``) puis exécute depuis la racine du dépôt :

```powershell
cd C:\Users\Pc\Desktop\hackathon
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:DJANGO_DEBUG = "true"
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py seed_hedera_demo
```

Note localement le mot de passe affiché une seule fois si le compte vient d’être créé. Le compte de démonstration est `hedera.demo@example.test`.

### 2. Lancer le backend avec un nouveau signer testnet

La clé privée que tu as publiée précédemment est compromise : révoque-la/remplace-la dans le portail Hedera avant de continuer. N’utilise jamais cette ancienne clé. Le nouvel opérateur doit être un compte **testnet** financé en HBAR de test, et sa nouvelle clé ECDSA doit être celle actuellement autorisée par ce compte. Saisis-la uniquement dans l’invite masquée ci-dessous — pas dans le chat, le navigateur, `.env.example` ou Git.

Dans le même terminal PowerShell, définis l’identifiant du compte opérateur correspondant à la clé remplacée et le compte destinataire testnet :

```powershell
$env:DJANGO_DEBUG = "true"
$env:FW_HEDERA_NETWORK = "testnet"
$env:FW_HEDERA_DEMO_OPERATOR_ACCOUNT_ID = "0.0.10685730"
$env:FW_HEDERA_DEMO_RECIPIENT_ACCOUNT_ID = "0.0.10868485"
$env:FW_MODE_EVIDENCE = "github"
$env:FW_GITHUB_ALLOWED_REPOSITORIES = "elve011/repo-test"
$secureKey = Read-Host "Nouvelle clé privée ECDSA du compte testnet" -AsSecureString
$env:FW_HEDERA_DEMO_OPERATOR_PRIVATE_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
.\.venv\Scripts\python.exe backend\manage.py runserver
```

Si la rotation de clé ou la création du compte a donné un nouvel identifiant opérateur, remplace `0.0.10685730` par cet identifiant. La clé doit être au format hexadécimal ECDSA secp256k1 de 32 octets (64 caractères hexadécimaux, préfixe `0x` accepté). Garde ce terminal ouvert pendant le test ; ferme-le après `Ctrl`+`C` pour effacer les variables d’environnement de cette session. La route de paiement refuse tout réseau autre que testnet et n’accepte qu’un montant exact de 0,1 HBAR.

### 3. Ouvrir le front et envoyer un paiement testnet

Ouvre un **deuxième** terminal PowerShell dans VS Code :

```powershell
cd C:\Users\Pc\Desktop\hackathon\frontend
npm run dev
```

Va sur <http://localhost:3000/login>, connecte-toi avec le compte démo, puis ouvre **Project Detail**. Les champs commit et PR sont préremplis avec le SHA `c3d98af7924dbd41c892d80597dde34d3718bddc` et la PR `#1` de `elve011/repo-test`. Clique **Vérifier via GitHub API** : les commits, PR, reviews et états CI sont lus côté backend. Dans un troisième terminal, depuis la racine, lance `.\.venv\Scripts\python.exe backend\manage.py process_events --once`, puis actualise la page. Au moment de la préparation, la PR #1 est ouverte et sans review ; son évaluation peut être `REJECTED` ou `UNKNOWN`, ce qui est attendu. Cela ne change pas les preuves de démonstration `TEST_ONLY`. Ensuite ouvre **Wallet & Settlements**, vérifie les comptes dans la confirmation et confirme le transfert réel de 0,1 HBAR testnet. Le reçu et le lien HashScan s’affichent après l’envoi. Chaque milestone ne peut être payé qu’une fois ; si l’issue réseau est incertaine, vérifie HashScan avant toute action de récupération et ne supprime pas manuellement l’enregistrement.

Si le bouton reste désactivé, le front affiche la cause de configuration. Vérifie `DEBUG=True`, `FW_HEDERA_NETWORK=testnet`, que la clé remplacée correspond au compte opérateur et qu’il dispose de HBAR testnet pour le transfert et les frais. **N’entre jamais une clé mainnet et ne configure jamais ces identifiants en production.**
