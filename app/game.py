"""Objectifs : points, niveaux, missions et paquets.

- Le journal `points` est la seule source de vérité : le niveau se déduit du total (paliers fixes).
- Chaque attribution a une référence unique (« grade:<note> », « mission:<id> ») : rejouer le calcul ne double jamais les points.
- Les points des notes ne comptent qu'à partir de l'activation (réglage `game_since`) : pas de rattrapage de l'historique.
"""
import json
import random
from datetime import date, timedelta

POINTS_PER_LEVEL = 10
MISSION_COUNT = 3          # missions actives en même temps
MISSION_DAYS = 21
# Liste provisoire : les vraies récompenses seront choisies par le parent. La rareté pilote l'animation d'ouverture.
RARITY_WEIGHTS = {"common": 50, "rare": 30, "epic": 15, "legendary": 5}
REWARDS = [
    {"label": "Une heure d'écran en plus", "rarity": "common", "icon": "⏰"},
    {"label": "Un jeu de société", "rarity": "common", "icon": "🎲"},
    {"label": "Une BD", "rarity": "common", "icon": "📖"},
    {"label": "Un livre", "rarity": "rare", "icon": "📚"},
    {"label": "Une soirée film au choix", "rarity": "rare", "icon": "🍿"},
    {"label": "Une sortie ciné", "rarity": "epic", "icon": "🎬"},
    {"label": "Un goûter au restaurant", "rarity": "epic", "icon": "🍔"},
    {"label": "Un jeu vidéo", "rarity": "legendary", "icon": "🎮"},
]
BY_LABEL = {r["label"]: r for r in REWARDS}


def grade_points(g: float) -> int:
    """Note sur 20 : 16-17 = 1 point, 18-19 = 2, 20 = 3."""
    return 3 if g >= 20 else 2 if g >= 18 else 1 if g >= 16 else 0


def level_info(total: int) -> dict:
    level, into = total // POINTS_PER_LEVEL + 1, total % POINTS_PER_LEVEL
    return {"points": total, "level": level, "into": into, "per_level": POINTS_PER_LEVEL,
            "pct": round(100 * into / POINTS_PER_LEVEL), "to_next": POINTS_PER_LEVEL - into}


def total_points(c) -> int:
    return c.execute("SELECT COALESCE(SUM(points), 0) FROM points").fetchone()[0]


def _setting(c, key, default=None):
    r = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return r[0] if r else default


def award(c, kind: str, ref: str, pts: int, label: str) -> bool:
    return c.execute("INSERT OR IGNORE INTO points (kind, ref, points, label) VALUES (?,?,?,?)", (kind, ref, pts, label)).rowcount == 1


def since(c) -> str:
    s = _setting(c, "game_since")
    if not s:
        s = date.today().isoformat()
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('game_since', ?)", (s,))
    return s


def award_grades(c) -> None:
    for g in c.execute("SELECT * FROM grades WHERE date >= ? AND grade >= 16", (since(c),)).fetchall():
        pts = grade_points(g["grade"])
        award(c, "grade", f"grade:{g['id']}", pts, f"{_pretty(g['subject'])} : {_fmt(g['grade'])}/20")


# ---- missions ----

def _current_averages(c) -> list:
    """Moyennes de la période la plus récente qui en a."""
    r = c.execute("SELECT period FROM averages JOIN periods ON periods.name = averages.period ORDER BY periods.position DESC LIMIT 1").fetchone()
    if not r:
        return []
    return [dict(x) for x in c.execute("SELECT * FROM averages WHERE period = ? AND student IS NOT NULL", (r["period"],))]


def _pretty(s: str) -> str:
    """« ED.PHYSIQUE &amp; SPORT. » -> « Ed.physique & sport. » (comme l'onglet Résultats)."""
    t = (s or "").replace("&amp;", "&").strip().lower()
    return t[:1].upper() + t[1:]


def _fmt(x) -> str:
    return f"{x:.1f}".replace(".", ",").rstrip("0").rstrip(",") if x is not None else "?"


def _candidates(c) -> list[dict]:
    avgs = _current_averages(c)
    out = []
    for a in avgs:
        if a["student"] is not None and a["student"] < 19:
            for delta, pts in ((0.5, 1), (1, 2), (2, 3)):
                out.append({"kind": "avg_up", "subject": a["subject"], "points": pts, "params": {"delta": delta},
                            "baseline": {"avg": a["student"], "period": a["period"]},
                            "label": f"Améliorer la moyenne de {_pretty(a['subject'])} de {_fmt(delta)} point{'s' if delta > 1 else ''}"})
        if a["class_avg"] is not None and a["student"] < a["class_avg"]:
            gap = a["class_avg"] - a["student"]
            out.append({"kind": "beat_class", "subject": a["subject"], "points": 1 if gap <= 1 else 2 if gap <= 2.5 else 3,
                        "params": {}, "baseline": {"avg": a["student"], "class_avg": a["class_avg"], "period": a["period"]},
                        "label": f"Dépasser la moyenne de la classe en {_pretty(a['subject'])}"})
    for n, t, pts in ((2, 14, 1), (3, 16, 2), (3, 18, 3)):
        out.append({"kind": "good_grades", "subject": None, "points": pts, "params": {"n": n, "min": t}, "baseline": {},
                    "label": f"Obtenir {n} notes d'au moins {t}/20 (n'importe quelle matière)"})
    return out


def generate(c, rng=random) -> int:
    """Complète jusqu'à MISSION_COUNT missions actives (types variés, jamais deux fois la même matière ni le même objectif)."""
    rows = c.execute("SELECT kind, subject, label FROM missions WHERE status = 'active'").fetchall()
    kinds = [r["kind"] for r in rows]
    labels = {r["label"] for r in rows}
    subjects = {r["subject"] for r in rows if r["subject"]}
    cands = _candidates(c)
    added = 0
    while len(kinds) < MISSION_COUNT:
        pool = [m for m in cands if m["label"] not in labels and (m["subject"] is None or m["subject"] not in subjects)]
        if not pool:
            break
        m = rng.choice([x for x in pool if x["kind"] not in kinds] or pool)      # on varie les types
        today = date.today()
        c.execute("INSERT INTO missions (kind, subject, params, baseline, points, label, started_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
                  (m["kind"], m["subject"], json.dumps(m["params"]), json.dumps(m["baseline"]), m["points"], m["label"],
                   today.isoformat(), (today + timedelta(days=MISSION_DAYS)).isoformat()))
        kinds.append(m["kind"]); labels.add(m["label"])
        if m["subject"]:
            subjects.add(m["subject"])
        added += 1
    return added


def progress(c, m) -> dict:
    """État d'une mission : {done, current, target, text}."""
    params, base = json.loads(m["params"]), json.loads(m["baseline"])
    if m["kind"] in ("avg_up", "beat_class"):
        r = c.execute("SELECT student, class_avg FROM averages WHERE period = ? AND subject = ?", (base["period"], m["subject"])).fetchone()
        cur = r["student"] if r and r["student"] is not None else base["avg"]
        if m["kind"] == "avg_up":
            gain = round(cur - base["avg"], 2)
            return {"done": gain >= params["delta"] - 1e-9, "current": max(gain, 0), "target": params["delta"],
                    "text": f"{_fmt(base['avg'])} → {_fmt(cur)} (objectif {_fmt(base['avg'] + params['delta'])})"}
        cl = r["class_avg"] if r and r["class_avg"] is not None else base["class_avg"]
        return {"done": cur > cl, "current": cur, "target": cl, "text": f"Toi {_fmt(cur)} · classe {_fmt(cl)}"}
    n = c.execute("SELECT COUNT(*) FROM grades WHERE date >= ? AND grade >= ?", (m["started_at"], params["min"])).fetchone()[0]
    return {"done": n >= params["n"], "current": min(n, params["n"]), "target": params["n"], "text": f"{min(n, params['n'])} / {params['n']}"}


def evaluate(c) -> None:
    today = date.today().isoformat()
    for m in c.execute("SELECT * FROM missions WHERE status = 'active'").fetchall():
        if progress(c, m)["done"]:
            c.execute("UPDATE missions SET status = 'done', done_at = ? WHERE id = ?", (today, m["id"]))
            award(c, "mission", f"mission:{m['id']}", m["points"], f"Mission réussie : {m['label']}")
        elif m["expires_at"] < today:
            c.execute("UPDATE missions SET status = 'expired' WHERE id = ?", (m["id"],))


# ---- paquets ----

def ensure_packs(c) -> None:
    level = level_info(total_points(c))["level"]
    for lv in range(2, level + 1):
        c.execute("INSERT OR IGNORE INTO packs (level) VALUES (?)", (lv,))


def open_pack(c, level: int, rng=random) -> dict | None:
    """Tire la rareté (pondérée) puis une récompense de cette rareté ; None si le paquet n'existe pas ou est déjà ouvert."""
    rarity = rng.choices(list(RARITY_WEIGHTS), weights=list(RARITY_WEIGHTS.values()))[0]
    reward = rng.choice([r for r in REWARDS if r["rarity"] == rarity])
    ok = c.execute("UPDATE packs SET opened_at = datetime('now'), reward = ?, rarity = ? WHERE level = ? AND opened_at IS NULL",
                   (reward["label"], reward["rarity"], level)).rowcount
    return dict(reward) if ok else None


def update(c) -> None:
    """À appeler après chaque synchro : points des notes, missions réussies / expirées, nouvelles missions, paquets."""
    since(c)
    award_grades(c)
    evaluate(c)
    generate(c)
    evaluate(c)   # une mission peut être remplie dès sa création (données déjà là)
    ensure_packs(c)


def summary(c) -> dict:
    info = level_info(total_points(c))
    info["packs"] = c.execute("SELECT COUNT(*) FROM packs WHERE opened_at IS NULL").fetchone()[0]
    return info


def overview(c) -> dict:
    missions = []
    for m in c.execute("SELECT * FROM missions ORDER BY (status = 'active') DESC, id DESC LIMIT 12").fetchall():
        d = {k: m[k] for k in ("id", "kind", "subject", "points", "label", "started_at", "expires_at", "status", "done_at")}
        d["progress"] = progress(c, m) if m["status"] == "active" else None
        missions.append(d)
    return {**summary(c), "missions": missions,
            "packs_list": [{**dict(r), "icon": BY_LABEL.get(r["reward"], {}).get("icon")} for r in c.execute("SELECT level, opened_at, reward, rarity FROM packs ORDER BY level DESC")],
            "history": [dict(r) for r in c.execute("SELECT at, points, label FROM points ORDER BY id DESC LIMIT 15")]}
