# StudyFun (devoirs, résultats et emploi du temps Pronote)

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

### Élèves et parents

- Un **compte élève** a ses propres données et son propre QR code Pronote (espace élève). Un **compte parent** est lié à un élève : il consulte ses devoirs, résultats et emploi du temps en lecture seule.
- Liaison : à l'inscription, le parent est rattaché automatiquement à l'élève dont l'identifiant Pronote figure parmi ses enfants (à défaut : même nom, classe et établissement). Secours : l'élève génère un code (menu de l'avatar → « Inviter un parent », valable 7 jours, usage unique) que le parent saisit en plus de son QR code. L'élève doit s'être connecté avec son QR code avant.
- Pour passer un compte existant d'un jeton parent à un jeton élève sans perdre l'historique : « Reconnecter Pronote » avec le QR code de l'élève (les cartes, l'avatar et les réglages sont conservés).

## Fond d'écran saisonnier

Le fond de l'app change avec la période de l'année : Noël (1er déc. → 6 janv.), hiver (7 janv. → 19 mars), printemps (20 mars → 20 juin), été (21 juin → 22 sept.), automne (23 sept. → 30 nov.). Le calendrier est dans le `<head>` de `app/templates/index.html` (tableau `DEBUT`, calculé dans le navigateur) ; `?saison=noel` dans l'adresse prévisualise une saison. L'image est voilée pour rester lisible (plus fortement en thème sombre, variable `--saison-veil`). Les images sources `fond-<saison>.png` se déposent à la racine (non versionnées) ; `.venv/bin/python scripts/build_saisons.py` écrit les versions web `app/static/saisons/<saison>.jpg` (1600 px, ~100 Ko).

## Notes (flux et « pas encore vues »)

Onglet « Notes » : toutes les notes (sur 20) avec date, coefficient, moyenne et max de la classe, commentaire. Une note qui arrive à la synchronisation est « non vue » **même si sa date est ancienne** (un enseignant peut saisir une note datée d'il y a un mois) : l'état est stocké côté serveur, dans la base de l'élève (colonnes `first_seen` et `seen_at` de `grades`, quelques octets par note, rien à synchroniser entre appareils). Les notes déjà connues au déploiement, ou lues à la toute première synchronisation, sont considérées comme vues. Elles sont mises en avant (section « Nouvelles notes », pastille rouge sur l'onglet) et marquées vues quand l'élève quitte l'onglet ou clique sur « Tout marquer comme vu ». Le parent voit ce qui n'a pas encore été vu, sans rien modifier.

## Objectifs (gamification)

- **Points :** chaque note de 16 ou plus (ramenée sur 20) rapporte 1 point (16-17), 2 (18-19) ou 3 (20) ; une mission réussie rapporte 1 à 3 points selon sa difficulté. Seules les notes postérieures à l'activation comptent (pas de rattrapage de l'historique). Le journal `points` est la source de vérité, une référence unique par événement évite tout doublon.
- **Niveaux :** paliers fixes de 10 points (`game.POINTS_PER_LEVEL`). Chaque niveau gagné donne un paquet à ouvrir ; la récompense est tirée au hasard dans une liste provisoire (`game.REWARDS`, chaque récompense a une rareté : commun, rare, épique ou légendaire, tirée avec `game.RARITY_WEIGHTS`) : les vraies récompenses seront choisies par le parent. Le paquet est fait de trois images superposées (`app/static/paquet/` : complet, corps, couvercle, générées par `scripts/build_paquet.py` à partir des `paquet-*.png` déposées à la racine, non versionnées ; le couvercle saute à l'explosion). L'ouverture est une animation plein écran (`static/packfx.js`) aux couleurs de la rareté ; elle respecte `prefers-reduced-motion`. Le son est synthétisé dans le navigateur (Web Audio, aucun fichier) : chute, montée de tension, explosion, puis arpège dont la richesse dépend de la rareté ; vibration sur mobile Android. Un bouton 🔊 / 🔇 en haut à gauche de l'écran d'ouverture le coupe (choix mémorisé). Les raretés épique et légendaire ont un final spectaculaire : bannière qui s'écrase, second flash, aura et étoiles en orbite, feux d'artifice (4 en épique, 14 en légendaire), pluie dorée et roulement de timbales / fanfare / chœur en légendaire.
- **Missions :** 3 actives en même temps, de types différents, tirées au hasard, valables 21 jours (`game.MISSION_DAYS`). Les barèmes sont en tête de `app/game.py` :
  - atteindre une moyenne ronde dans une matière : à 13,4 on propose 14, 15 ou 16 ; points selon l'écart avec la moyenne actuelle (jusqu'à 0,5 = 1 pt, 1 = 2, 2 = 4, 3 = 6), cible à moins de 0,3 écartée (`game.AVG_UP`, `AVG_UP_MIN_GAP`) ; tirage pondéré en faveur des moyennes basses et des cibles proches (poids = (20 − moyenne)² / rang de la cible, `AVG_UP_WEIGHT`) : « 15 en maths » à 13,6 sort environ 5 fois plus souvent que « 19 en physique » à 18 ;
  - dépasser la moyenne de la classe dans une matière (proposé seulement si on est en dessous) : écart jusqu'à 1 = 2 pts, jusqu'à 2 = 4, au-delà = 5 ;
  - atteindre une moyenne générale ronde ou à .5 (à 14,3 : 14,5 ou 15) ; points selon l'écart : jusqu'à 0,3 = 2 pts, 0,5 = 5, 0,75 = 7, 1 = 10 ; cible à moins de 0,2 écartée (`game.OVERALL_UP`, `OVERALL_UP_MIN_GAP`) ;
  - notes au-dessus de la moyenne de la classe (note > moyenne de l'épreuve) : 2 notes = 1 pt, 5 notes = 3 ;
  - notes élevées : 3 notes ≥ 16 = 2 pts, 3 notes ≥ 18 = 5, 3 notes de 20 = 10.
  Seules les notes postérieures au début de la mission comptent.
- **Affichage :** onglet « Objectifs », niveau et barre de progression sur l'avatar (le parent consulte, sans ouvrir les paquets).

### Célébration d'une mission réussie

Quand une mission est validée (à la synchro), l'élève la voit célébrée **à la prochaine ouverture de l'app** (ou au retour dans l'app) : trophée, confettis, points gagnés, petit « ta-da » synthétisé et, s'il y a un paquet à ouvrir, un bouton pour aller l'ouvrir. Une seule fois par mission, quel que soit l'appareil (colonne `celebrated_at` de `missions`, `POST /api/missions/celebrated`) ; les missions déjà réussies avant cette fonction ne sont pas célébrées. Le parent ne voit pas la célébration (elle reste pour l'élève).

### Remise à plat des objectifs d'un élève

Quand les barèmes changent, `docker compose exec app python -m app.reset_game <identifiant> --after 2026-09-29` simule (rien n'est écrit), puis avec `--apply` : sauvegarde la base (`devoirs.db.avant-reset-<date>` dans le dossier de l'utilisateur), supprime les missions actives et en tire 3 nouvelles, compte dans les points les notes datées après la date donnée (sans doublon avec les points déjà attribués) et les remet en « pas encore vues ». Niveaux et paquets suivent.

### Compte administrateur (tests)

- `docker compose exec app python -m app.admin create <identifiant>` (le mot de passe est demandé) crée un compte qui se comporte comme un élève, sans QR code ni synchro Pronote, avec des données de démonstration (moyennes, emploi du temps, notes).
- Dans « Objectifs », une section « Outils de test » permet de s'octroyer 1, 3, 10 ou 25 points (niveaux et paquets suivent). Il peut aussi générer un code de liaison pour tester un compte parent. Le bouton « 🏆 Simuler une mission réussie » ajoute 5 points et déclenche la célébration d'une mission.
- Ce rôle ne peut pas être demandé depuis la page d'inscription.
