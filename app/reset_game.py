"""Remise à plat de l'état « Objectifs » d'un élève (opération manuelle, à lancer sur le serveur).

Usage (dans le conteneur) :
    docker compose exec app python -m app.reset_game <identifiant> --after 2026-09-29          # simulation, rien n'est écrit
    docker compose exec app python -m app.reset_game <identifiant> --after 2026-09-29 --apply  # sauvegarde la base puis applique

Effets :
- les missions actives sont supprimées et 3 nouvelles sont tirées selon les barèmes actuels (les missions déjà réussies et leurs points sont conservées) ;
- toute note datée APRÈS la date donnée est comptée dans les points (réglage `game_since` avancé au jour suivant, jamais reculé) et repasse en « pas encore vue » ;
- les niveaux et paquets suivent le nouveau total de points. Les points déjà attribués ne sont jamais comptés deux fois.
"""
import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta

from . import accounts, db, game


def _state(c) -> dict:
    return {"points": game.total_points(c), "level": game.level_info(game.total_points(c))["level"],
            "packs": c.execute("SELECT COUNT(*) FROM packs WHERE opened_at IS NULL").fetchone()[0],
            "missions": [r["label"] for r in c.execute("SELECT label FROM missions WHERE status = 'active' ORDER BY id")]}


def reset(c, after: str) -> dict:
    """Applique la remise à plat sur la connexion c (sans valider) et retourne un compte rendu."""
    first = (date.fromisoformat(after) + timedelta(days=1)).isoformat()   # « après le 29/09 » : à partir du 30/09
    before = _state(c)
    last = c.execute("SELECT COALESCE(MAX(id), 0) FROM points").fetchone()[0]
    cur = game._setting(c, "game_since")
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('game_since', ?)", (min(cur, first) if cur else first,))
    unseen = c.execute("UPDATE grades SET seen_at = NULL WHERE date >= ?", (first,)).rowcount
    c.execute("DELETE FROM missions WHERE status = 'active'")
    game.update(c)
    new_pts = [dict(r) for r in c.execute("SELECT points, label FROM points WHERE kind = 'grade' AND id > ? ORDER BY id", (last,))]
    return {"before": before, "after": _state(c), "unseen": unseen, "new_points": new_pts,
            "missions": [dict(r) for r in c.execute("SELECT label, points FROM missions WHERE status = 'active' ORDER BY id")]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("login", help="identifiant du compte élève")
    ap.add_argument("--after", required=True, help="les notes datées après ce jour (AAAA-MM-JJ) sont comptées comme nouvelles")
    ap.add_argument("--apply", action="store_true", help="écrire réellement (sinon simulation)")
    a = ap.parse_args(argv)
    date.fromisoformat(a.after)
    accounts.init()
    with accounts._conn() as ac:
        row = ac.execute("SELECT id, role FROM users WHERE login = ?", (accounts.normalize(a.login),)).fetchone()
    if not row or row["role"] not in ("student", "admin"):
        print("Compte élève introuvable :", a.login); return 1
    with db.as_user(row["id"]):
        db.init()
        if a.apply:
            dest = os.path.join(db.user_dir(), f"devoirs.db.avant-reset-{datetime.now():%Y%m%d-%H%M%S}")
            src = sqlite3.connect(db.db_path()); dst = sqlite3.connect(dest)
            with dst: src.backup(dst)
            src.close(); dst.close()
            print("Sauvegarde :", dest)
        c = db.conn()
        try:
            r = reset(c, a.after)
            c.commit() if a.apply else c.rollback()
        finally:
            c.close()
    b, n = r["before"], r["after"]
    print("APPLIQUÉ" if a.apply else "SIMULATION (rien n'est écrit ; relancer avec --apply)")
    print(f"Points : {b['points']} -> {n['points']} (niveau {b['level']} -> {n['level']}), paquets à ouvrir : {b['packs']} -> {n['packs']}")
    print(f"Notes repassées en « pas encore vues » : {r['unseen']} ; notes qui rapportent des points : {len(r['new_points'])}")
    for p in r["new_points"]: print(f"  +{p['points']}  {p['label']}")
    print("Anciennes missions supprimées :"); [print("  -", m) for m in b["missions"]]
    print("Nouvelles missions :"); [print(f"  + {m['label']} ({m['points']} pts)") for m in r["missions"]]
    return 0


if __name__ == "__main__":
    sys.exit(main())
