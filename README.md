# Devoirs Pronote

Webapp (FastAPI + SQLite) qui synchronise les devoirs depuis Pronote (via pronotepy, API non officielle),
les garde en local et renvoie le statut « terminé » vers Pronote.

## Démarrage

1. Dans Pronote (compte parent ou élève) : générer un QR code d'application mobile + un PIN à 4 chiffres.
   Décoder le QR code en JSON (`zbarimg --raw qr.png > qr.json`).
2. Initialiser les identifiants (le QR code expire vite) :
   ```
   docker compose build
   docker compose run --rm app python -m app.login /data/qr.json 1234
   ```
   (placer `qr.json` dans `./data/` avant, ou passer le JSON entre apostrophes à la place du chemin.)
3. `docker compose up -d` puis ouvrir http://localhost:8000

## Fonctionnement
- Synchro au démarrage puis toutes les `SYNC_INTERVAL_MIN` minutes, et à chaque bascule d'un devoir.
- Fenêtre lue : 7 jours passés → 90 jours à venir. Les devoirs déjà en base ne sont jamais supprimés.
- Cocher un devoir dans l'app le marque « en attente d'envoi » ; la synchro suivante l'envoie à Pronote.
  Tant que l'envoi n'a pas eu lieu, l'état de l'app prévaut.
- `./data` contient `devoirs.db` et `credentials.json` (jeton réécrit à chaque connexion) : à sauvegarder, et à ne pas partager.
- Si le jeton expire : refaire l'étape 2.
- API JSON : `GET /api/homework`.
