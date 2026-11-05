# Brief — Webapp « Devoirs Pronote »

À lire en entier avant de toucher au code. Coller ce fichier (ou `claude` dans le dossier du projet) comme contexte initial.

## Objectif
Parent d'une collégienne/lycéenne : récupérer automatiquement ses devoirs depuis Pronote, les stocker **en local** (persistance), les suivre dans ma propre webapp, et pouvoir **marquer « terminé »** depuis l'app avec répercussion dans Pronote.

## Contraintes et décisions déjà prises
- Pas d'API officielle exploitable (l'API HYPERPLANNING est réservée aux établissements). On utilise une API **non officielle** : `pronotepy` (Python, en mode maintenance). Alternative active : Pawnote (JS/TS), à envisager si pronotepy casse.
- Connexion Pronote via **ENT**, mais le **QR code mobile** fonctionne : on s'en sert pour obtenir un jeton réutilisable (pas de mot de passe stocké). Le jeton change à chaque connexion → toujours réécrire `credentials.json` après `token_login`.
- Compte visé : **parent** (préférable). Si Pronote refuse l'écriture « fait » côté parent, basculer sur le QR code du compte élève.
- Stack : Python 3.12, FastAPI, SQLite (stdlib), Jinja2, uvicorn. Déploiement : **image Docker** + docker-compose, volume `./data:/data`.
- Pas de préférence de langage de ma part ; priorité à la simplicité et à la robustesse.

## État actuel (code livré et testé avec un faux client)
```
app/db.py          schéma SQLite (homework, sync_log), DATA_DIR=/data
app/sync.py        get_client() (injectable), _sync(), run_sync() avec verrou
app/login.py       python -m app.login <qr.json|chemin> <PIN> -> écrit credentials.json
app/main.py        FastAPI : /, /toggle/{id}, /sync, /api/homework ; boucle de synchro ; Basic auth optionnelle
app/templates/index.html
tests/test_app.py  test avec faux client Pronote (pas de réseau)
Dockerfile, docker-compose.yml, requirements.txt, README.md
```
Logique de synchro (`app/sync.py`) :
1. Lit les devoirs de J-7 à J+90.
2. **Push d'abord** : pour chaque ligne `pending_push=1`, appelle `hw.set_done(...)` si l'état Pronote diffère, puis efface le flag.
3. **Pull ensuite** : insert/update par `hw.id` ; si `pending_push` est encore à 1, l'état local est conservé.
4. Rien n'est jamais supprimé de la base. Résultat journalisé dans `sync_log` (affiché en bas de page, rouge si erreur).
- Déclencheurs : démarrage, toutes les `SYNC_INTERVAL_MIN` min (0 = désactivé), après chaque bascule, bouton « Synchroniser maintenant ».
- Config par env : `SYNC_INTERVAL_MIN`, `APP_USER`, `APP_PASSWORD` (vide = pas d'auth), `CHILD_NAME` (compte parent), `DATA_DIR`, `TZ`.

## Ce qui n'a PAS été vérifié (à faire en premier)
1. **Connexion réelle** : `pronotepy.Client.qrcode_login(qr, pin, uuid)` dans `app/login.py` — la signature dépend de la version de pronotepy (vérifier `pip show pronotepy` et la doc). Alternative : `python -m pronotepy.create_login`.
2. **`set_done()` avec un compte parent** : à tester sur un vrai devoir ; sinon utiliser le compte élève.
3. **`set_child`** pour un compte parent (nom exact de l'enfant).
4. `docker build` jamais exécuté (pas de Docker dans l'environnement où le code a été écrit).
5. Encodage/format de `hw.description` (HTML ? pièces jointes `hw.files` ignorées pour l'instant).
6. Comportement des `hw.id` : stables d'une synchro à l'autre ? (la clé primaire en dépend).

## Prochaines étapes suggérées (par priorité)
1. Faire tourner le test : `pip install -r requirements.txt httpx && python tests/test_app.py`.
2. Construire l'image, faire la connexion QR, première synchro réelle, corriger ce qui diffère.
3. Gestion propre de l'expiration du jeton (message clair + bannière dans l'UI).
4. Notifications (mail/Telegram/ntfy) pour devoirs en retard ou veille de rendu.
5. Afficher pièces jointes / liens ; filtre par matière ; vue semaine.
6. Tests unitaires supplémentaires (conflits push/pull, devoir disparu de Pronote).
7. Éventuellement : multi-enfants, sauvegarde de `./data`, reverse proxy HTTPS si exposé hors réseau local.

## Règles de travail
- Données d'un mineur + jeton d'accès : ne jamais committer `data/`, `credentials.json`, ni de QR code (ajouter un `.gitignore`).
- Ne pas désactiver l'authentification si l'app est exposée hors réseau local.
- Ne pas faire de requêtes agressives vers Pronote (synchro ≥ 15 min, pas de boucle serrée) pour éviter un blocage du compte.
- Garder `get_client()` injectable pour pouvoir tester sans réseau.
- Réponses en français, concises.
