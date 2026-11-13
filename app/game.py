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
# Barèmes des missions (à ajuster ici)
AVG_UP = [(0.5, 1), (1, 2), (2, 4), (3, 6)]       # (écart maximal entre la moyenne actuelle et la cible, points) ; au-delà : pas proposé
AVG_UP_WEIGHT = 2                                 # poids d'une cible = (20 − moyenne)^AVG_UP_WEIGHT / rang de la cible : les moyennes basses et les cibles proches sortent bien plus souvent
AVG_UP_MIN_GAP = 0.3                              # écart minimal : on ne propose pas « 14 » à qui a déjà 13,9
BEAT_CLASS = [(1, 2), (2, 4), (None, 5)]          # (écart maximal avec la moyenne de la classe, points) ; None = au-delà
OVERALL_UP = [(0.3, 2), (0.5, 5), (0.75, 7), (1, 10)]        # (écart maximal entre la moyenne générale et la cible, points) ; cibles par demi-point (plus dur à faire bouger)
OVERALL_UP_MIN_GAP = 0.2
GRADES_ABOVE_CLASS = [(2, 1), (5, 3)]             # (nombre de notes au-dessus de la moyenne de la classe, points)
GOOD_GRADES = [(3, 16, 2), (3, 18, 5), (3, 20, 10)]   # (nombre de notes, note minimale sur 20, points)
# Liste provisoire : les vraies récompenses seront choisies par le parent. La rareté pilote l'animation d'ouverture.
RARITY_WEIGHTS = {"common": 50, "rare": 30, "epic": 15, "legendary": 5}
REWARDS = [   # les crédits sont des jetons de poker qui s'échangent contre du temps d'écran
    {"label": "1 h d'écran gratuite", "rarity": "common", "icon": "⏰"},
    {"label": "5 crédits gratuits", "rarity": "common", "icon": "🪙"},
    {"label": "Apéro chips et boisson ce soir", "rarity": "common", "icon": "🥤"},
    {"label": "2 h d'écran gratuites", "rarity": "rare", "icon": "⏳"},
    {"label": "10 crédits gratuits", "rarity": "rare", "icon": "🪙"},
    {"label": "Un repas livré au choix", "rarity": "rare", "icon": "🍕"},
    {"label": "Un livre de poche", "rarity": "rare", "icon": "📖"},
    {"label": "Un brunch en famille", "rarity": "epic", "icon": "🥐"},
    {"label": "Une soirée ciné en famille (film au choix)", "rarity": "epic", "icon": "🎬"},
    {"label": "20 crédits gratuits", "rarity": "epic", "icon": "💰"},
    {"label": "Un livre relié ou une BD", "rarity": "epic", "icon": "📚"},
    {"label": "Un jeu vidéo au choix (prix raisonnable)", "rarity": "legendary", "icon": "🎮"},
    {"label": "Un super crédit", "rarity": "legendary", "icon": "💎"},
    {"label": "Un vêtement au choix (prix raisonnable)", "rarity": "legendary", "icon": "👕"},
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

def _current_period(c):
    """Période la plus récente qui a des moyennes."""
    return c.execute("SELECT periods.* FROM periods WHERE EXISTS (SELECT 1 FROM averages WHERE averages.period = periods.name) "
                     "ORDER BY position DESC LIMIT 1").fetchone()


def _current_averages(c) -> list:
    p = _current_period(c)
    return [dict(x) for x in c.execute("SELECT * FROM averages WHERE period = ? AND student IS NOT NULL", (p["name"],))] if p else []


def _pretty(s: str) -> str:
    """« ED.PHYSIQUE &amp; SPORT. » -> « Ed.physique & sport. » (comme l'onglet Résultats)."""
    t = (s or "").replace("&amp;", "&").strip().lower()
    return t[:1].upper() + t[1:]


def _fmt(x) -> str:
    return f"{x:.1f}".replace(".", ",").rstrip("0").rstrip(",") if x is not None else "?"


def _candidates(c) -> list[dict]:
    out = []
    for a in _current_averages(c):
        subj = _pretty(a["subject"])
        for target in range(int(a["student"]) + 1, 21):       # cibles rondes : 13,4 -> 14, 15, 16…
            gap = target - a["student"]
            if gap < AVG_UP_MIN_GAP - 1e-9:
                continue
            pts = next((p for limit, p in AVG_UP if gap <= limit), None)
            if pts is None:
                break
            weight = (20 - a["student"]) ** AVG_UP_WEIGHT / (target - int(a["student"]))   # 13,6 -> 15 : ~21 ; 18 -> 19 : 4
            out.append({"kind": "avg_up", "subject": a["subject"], "points": pts, "params": {"target": target}, "weight": weight,
                        "baseline": {"avg": a["student"], "period": a["period"]},
                        "label": f"Atteindre {target} de moyenne en {subj}"})
        if a["class_avg"] is not None and a["student"] < a["class_avg"]:
            gap = a["class_avg"] - a["student"]
            pts = next(p for limit, p in BEAT_CLASS if limit is None or gap <= limit)
            out.append({"kind": "beat_class", "subject": a["subject"], "points": pts, "params": {},
                        "baseline": {"avg": a["student"], "class_avg": a["class_avg"], "period": a["period"]},
                        "label": f"Dépasser la moyenne de la classe en {subj}"})
    per = _current_period(c)
    if per and per["overall"] is not None:
        ov, k = per["overall"], int(per["overall"] * 2) + 1
        while k <= 40:                                         # cibles rondes ou à .5 : 14,3 -> 14,5 ; 15 ; 15,5
            target = k / 2; k += 1
            gap = target - ov
            if gap < OVERALL_UP_MIN_GAP - 1e-9:
                continue
            pts = next((p for limit, p in OVERALL_UP if gap <= limit), None)
            if pts is None:
                break
            out.append({"kind": "overall_up", "subject": None, "points": pts, "params": {"target": target},
                        "baseline": {"avg": ov, "period": per["name"]}, "label": f"Atteindre {_fmt(target)} de moyenne générale"})
    for n, pts in GRADES_ABOVE_CLASS:
        out.append({"kind": "above_class", "subject": None, "points": pts, "params": {"n": n}, "baseline": {},
                    "label": f"Obtenir {n} notes au-dessus de la moyenne de la classe (n'importe quelle matière)"})
    for n, t, pts in GOOD_GRADES:
        what = "de 20/20" if t >= 20 else f"d'au moins {t}/20"
        out.append({"kind": "good_grades", "subject": None, "points": pts, "params": {"n": n, "min": t}, "baseline": {},
                    "label": f"Obtenir {n} notes {what} (n'importe quelle matière)"})
    return out


def generate(c, rng=random) -> int:
    """Complète jusqu'à MISSION_COUNT missions actives : on tire d'abord un type (en évitant ceux déjà actifs),
    puis une mission de ce type ; jamais deux fois la même matière ni le même objectif."""
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
        available = sorted({m["kind"] for m in pool})
        kind = rng.choice([k for k in available if k not in kinds] or available)
        same = [x for x in pool if x["kind"] == kind]
        m = rng.choices(same, weights=[x.get("weight", 1) for x in same])[0]
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
            goal = params["target"] if "target" in params else base["avg"] + params["delta"]   # « delta » : missions créées avant les cibles rondes
            return {"done": cur >= goal - 1e-9, "current": max(round(cur - base["avg"], 2), 0), "target": round(goal - base["avg"], 2),
                    "text": f"{_fmt(base['avg'])} → {_fmt(cur)} (objectif {_fmt(goal)})"}
        cl = r["class_avg"] if r and r["class_avg"] is not None else base["class_avg"]
        return {"done": cur > cl, "current": cur, "target": cl, "text": f"Toi {_fmt(cur)} · classe {_fmt(cl)}"}
    if m["kind"] == "overall_up":
        r = c.execute("SELECT overall FROM periods WHERE name = ?", (base["period"],)).fetchone()
        cur = r["overall"] if r and r["overall"] is not None else base["avg"]
        goal = params["target"] if "target" in params else base["avg"] + params["delta"]
        return {"done": cur >= goal - 1e-9, "current": max(round(cur - base["avg"], 2), 0), "target": round(goal - base["avg"], 2),
                "text": f"{_fmt(base['avg'])} → {_fmt(cur)} (objectif {_fmt(goal)})"}
    if m["kind"] == "above_class":
        n = c.execute("SELECT COUNT(*) FROM grades WHERE date >= ? AND class_avg IS NOT NULL AND grade > class_avg", (m["started_at"],)).fetchone()[0]
    else:   # good_grades
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


def set_delivered(c, level: int, delivered: bool) -> bool:
    """Le parent coche (ou décoche) une récompense remise ; seulement pour un paquet ouvert."""
    return c.execute("UPDATE packs SET delivered_at = " + ("datetime('now')" if delivered else "NULL") +
                     " WHERE level = ? AND opened_at IS NOT NULL", (level,)).rowcount == 1


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
            "packs_list": [{**dict(r), "icon": BY_LABEL.get(r["reward"], {}).get("icon")} for r in c.execute("SELECT level, opened_at, reward, rarity, delivered_at FROM packs ORDER BY level DESC")],
            "history": [dict(r) for r in c.execute("SELECT at, points, label FROM points ORDER BY id DESC LIMIT 15")]}
