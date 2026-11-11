# Devoirs Pronote

Webapp (FastAPI + SQLite) qui synchronise les devoirs depuis Pronote (via pronotepy, API non officielle),
les garde en local et renvoie le statut « terminé » vers Pronote.

## Démarrage

1. Copier `.env.example` en `.env` et le remplir (`INVITE_CODE`…), puis `docker compose up -d --build`
   et ouvrir l'application.
2. **Première connexion à Pronote** : un bandeau rouge propose « Reconnecter Pronote ». Dans Pronote (compte parent
   ou élève), générer un QR code d'application mobile + un PIN à 4 chiffres, en faire une **capture d'écran**, la
   déposer dans la fenêtre (ou la coller avec Ctrl/⌘ + V), saisir le PIN. Le QR code expire vite : enchaîner sans attendre.
   Même procédure à chaque expiration du jeton, depuis n'importe quel appareil.
   Équivalent en ligne de commande : `docker compose run --rm app python -m app.login /data/capture.png 1234`
   (la capture, ou un fichier/texte JSON du QR code, doit être lisible depuis le conteneur, par ex. dans `./data/`).

## Fonctionnement
- Synchro au démarrage puis toutes les `SYNC_INTERVAL_MIN` minutes, et à chaque bascule d'un devoir.
- Fenêtre lue : 7 jours passés → 90 jours à venir. Les devoirs déjà en base ne sont jamais supprimés.
- Cocher un devoir dans l'app le marque « en attente d'envoi » ; la synchro suivante l'envoie à Pronote.
  Tant que l'envoi n'a pas eu lieu, l'état de l'app prévaut.
- `./data` contient `devoirs.db` et `credentials.json` (jeton réécrit à chaque connexion) : à sauvegarder, et à ne pas partager.
- Si le jeton expire : refaire l'étape 2 (bouton « Reconnecter Pronote »). L'application affiche alors un **bandeau rouge** en haut de page, et envoie
  (si `NOTIFY_URL` est défini) **une** notification, puis une autre à la reconnexion. Le message ne contient aucune donnée
  de devoirs. `NOTIFY_URL` accepte un topic [ntfy](https://ntfy.sh) (`https://ntfy.sh/<topic-secret>` ou votre serveur) ;
  `NOTIFY_TOKEN` est facultatif.
- La reconnexion par capture exige d'être connecté, ne conserve ni la capture ni le QR code
  (seul `credentials.json` est écrit), refuse les adresses non HTTPS ou internes et tout autre serveur Pronote que
  celui déjà configuré. `ALLOW_RECONNECT=0` la désactive (utilisé par `dev.sh`).
- API JSON : `GET /api/homework`.

## Comptes (multi-utilisateur)

- Pages `/login` et `/register` ; session par cookie (180 jours), mots de passe hachés (scrypt). Fonctionne aussi dans la PWA installée.
- Inscription : identifiant, mot de passe, code d'invitation (`INVITE_CODE`), capture du QR code Pronote + PIN, prénom de l'enfant si compte parent.
- Chaque compte a sa base, son jeton Pronote et ses fichiers dans `data/users/<id>/` ; la synchro tourne pour tous les comptes.
- Migration : au premier démarrage, le premier compte créé récupère l'ancienne installation (`data/devoirs.db`, `credentials.json`, `files/`) ; son QR code est alors facultatif.
- Sauvegarder tout `data/` (y compris `accounts.db`). `APP_USER` / `APP_PASSWORD` ne servent plus.
