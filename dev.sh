#!/usr/bin/env bash
# Serveur de développement local.
#
# NE SE CONNECTE JAMAIS À PRONOTE : le jeton est celui du serveur de production, et chaque
# connexion le change (un second client le déconnecterait). On travaille donc sur une copie
# des données, sans credentials.json, sans synchro automatique et sans écriture vers Pronote.
#
# Usage :  ./dev.sh            démarre (copie data/ vers data-dev/ la première fois)
#          ./dev.sh reset      repart d'une copie fraîche des données
# Options (variables d'environnement) :
#          PORT=8001           autre port (défaut 8000)
#          SRC_DB=chemin       base à copier au lieu de data/devoirs.db (ex. celle récupérée du serveur)
#          CHILD_NAME="..."    nom affiché dans le titre
set -euo pipefail
cd "$(dirname "$0")"

DEV=data-dev
PORT="${PORT:-8000}"
SRC_DB="${SRC_DB:-data/devoirs.db}"

[ -x .venv/bin/uvicorn ] || {
  echo "Environnement Python introuvable (.venv). Voir README : python 3.12, puis pip install -r requirements.txt" >&2
  exit 1
}

[ "${1:-}" = "reset" ] && rm -rf "$DEV"

if [ ! -f "$DEV/devoirs.db" ]; then
  mkdir -p "$DEV"
  if [ -f "$SRC_DB" ]; then
    cp "$SRC_DB" "$DEV/devoirs.db"
    src_files="$(dirname "$SRC_DB")/files"
    [ -d "$src_files" ] && cp -r "$src_files" "$DEV/files"
    echo "Données copiées depuis $SRC_DB vers $DEV/"
  else
    echo "Aucune base à copier ($SRC_DB) : démarrage avec une base vide dans $DEV/"
  fi
fi

# garde-fou : aucun identifiant Pronote ne doit exister dans le dossier de dev
rm -f "$DEV/credentials.json" "$DEV/credentials.json.tmp"

export DATA_DIR="$PWD/$DEV"
export SYNC_INTERVAL_MIN=0          # aucune synchro, même au démarrage
export PUSH_TO_PRONOTE=0
export ALLOW_RECONNECT=0            # jamais de connexion à Pronote depuis le poste de dev
export APP_PASSWORD=""              # pas d'authentification en local (ne pas charger .env)
export CHILD_NAME="${CHILD_NAME:-}"

# pas de Pronote en dev : moyennes et emploi du temps fictifs, seulement là où la base copiée n'en a pas
.venv/bin/python -m app.demo >/dev/null

echo "Dev sur http://127.0.0.1:$PORT  (données : $DEV/, pas de Pronote)"
exec .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port "$PORT"
