import os, tempfile, sys, json, random
from datetime import date, timedelta
from types import SimpleNamespace as NS
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["AUTH_DISABLED"] = "1"
os.environ["SYNC_INTERVAL_MIN"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
from app import db, game, sync
from app.main import app

today = date.today()
iso = lambda n: (today - timedelta(days=n)).isoformat()

# --- barème des notes et niveaux (paliers fixes) ---
assert [game.grade_points(x) for x in (15.9, 16, 17.9, 18, 19.5, 20)] == [0, 1, 1, 2, 2, 3]
assert game.level_info(0)["level"] == 1 and game.level_info(9)["pct"] == 90
i = game.level_info(25); assert (i["level"], i["into"], i["to_next"]) == (3, 5, 5)

# --- notes lues dans Pronote : ramenées sur 20, absences ignorées, doublons distingués ---
class G:
    def __init__(s, grade, out_of, d, subj="MATHS", coef="1", avg="12", mx="18"): s.grade=grade; s.out_of=out_of; s.date=d; s.subject=NS(name=subj); s.coefficient=coef; s.average=avg; s.max=mx; s.comment=None
period = NS(name="Trimestre 1", start=today - timedelta(days=60), grades=[G("8", "10", today), G("8", "10", today), G("Absent", "20", today), G("17,5", "20", today - timedelta(days=1))])
future = NS(name="Trimestre 3", start=today + timedelta(days=60), grades=[G("20", "20", today)])
db.init()
assert sync._sync_grades(NS(periods=[period, future])) == 3
sync._sync_grades(NS(periods=[period, future]))   # rejouer ne duplique rien
with db.conn() as c:
    rows = c.execute("SELECT grade, class_avg FROM grades ORDER BY grade").fetchall()
    assert [r["grade"] for r in rows] == [16, 16, 17.5] and rows[0]["class_avg"] == 24, [dict(r) for r in rows]  # 8/10 -> 16/20

    # --- points : seulement depuis l'activation, une seule fois par note ---
    c.execute("INSERT OR REPLACE INTO settings VALUES ('game_since', ?)", (iso(0),))
    game.award_grades(c); game.award_grades(c)
    assert game.total_points(c) == 2, "deux notes de 16 aujourd'hui = 2 pts ; la note d'hier est antérieure à l'activation"
    c.execute("INSERT OR REPLACE INTO settings VALUES ('game_since', ?)", (iso(2),))
    game.award_grades(c); assert game.total_points(c) == 3, "la note d'hier compte maintenant (+1), les autres ne sont pas recomptées"

    # --- missions ---
    c.execute("INSERT INTO periods (name, position) VALUES ('Trimestre 1', 0)")
    for s, st, cl in (("MATHEMATIQUES", 12.0, 11.0), ("ANGLAIS", 10.0, 12.5), ("SVT", 15.0, 13.0), ("ARTS", 14.0, 14.5)):
        c.execute("INSERT INTO averages (period, subject, student, class_avg) VALUES ('Trimestre 1', ?, ?, ?)", (s, st, cl))
    random.seed(1)
    game.update(c)
    ms = c.execute("SELECT * FROM missions WHERE status = 'active'").fetchall()
    assert len(ms) == 3 and len({m["kind"] for m in ms}) == 3, [m["label"] for m in ms]
    assert all(m["subject"] not in ("MATHEMATIQUES", "SVT") for m in ms if m["kind"] == "beat_class"), "dépasser la classe : seulement où on est en dessous"
    n = c.execute("SELECT COUNT(*) FROM missions").fetchone()[0]; game.update(c); assert c.execute("SELECT COUNT(*) FROM missions").fetchone()[0] == n

    # progression « moyenne » : baseline mémorisée, objectif atteint -> points une seule fois
    c.execute("DELETE FROM missions")
    c.execute("INSERT INTO missions (kind, subject, params, baseline, points, label, started_at, expires_at) VALUES ('avg_up','MATHEMATIQUES',?,?,2,'+1 en maths',?,?)",
              (json.dumps({"delta": 1}), json.dumps({"avg": 12.0, "period": "Trimestre 1"}), iso(5), iso(-10)))
    m = c.execute("SELECT * FROM missions").fetchone()
    assert game.progress(c, m)["done"] is False
    c.execute("UPDATE averages SET student = 12.6 WHERE subject = 'MATHEMATIQUES'"); assert game.progress(c, m)["done"] is False
    c.execute("UPDATE averages SET student = 13.0 WHERE subject = 'MATHEMATIQUES'")
    before = game.total_points(c); game.evaluate(c); game.evaluate(c)
    assert c.execute("SELECT status FROM missions WHERE id = ?", (m["id"],)).fetchone()[0] == "done" and game.total_points(c) == before + 2

    # « 3 notes ≥ 16 » : seules les notes postérieures au début de la mission comptent
    c.execute("DELETE FROM missions")
    c.execute("INSERT INTO missions (kind, params, baseline, points, label, started_at, expires_at) VALUES ('good_grades',?,'{}',2,'3 notes',?,?)",
              (json.dumps({"n": 3, "min": 16}), iso(0), iso(-10)))
    m = c.execute("SELECT * FROM missions").fetchone(); assert game.progress(c, m)["current"] == 2   # les deux 16 d'aujourd'hui ; 17,5 d'hier exclue
    c.execute("INSERT INTO grades (id, period, subject, date, grade) VALUES ('x','T1','SVT',?,18)", (iso(0),))
    assert game.progress(c, m)["done"] is True
    # expiration
    c.execute("INSERT INTO missions (kind, params, baseline, points, label, started_at, expires_at) VALUES ('good_grades',?,'{}',2,'trop tard',?,?)",
              (json.dumps({"n": 9, "min": 16}), iso(30), iso(1)))
    game.evaluate(c); assert c.execute("SELECT status FROM missions WHERE label = 'trop tard'").fetchone()[0] == "expired"

    # --- niveaux et paquets : un paquet par niveau, ouvert une seule fois ---
    c.execute("DELETE FROM points"); game.award(c, "mission", "t1", 25, "test")
    game.ensure_packs(c); game.ensure_packs(c)
    assert [r[0] for r in c.execute("SELECT level FROM packs ORDER BY level")] == [2, 3]
    r = game.open_pack(c, 2); assert r in game.REWARDS and c.execute("SELECT rarity FROM packs WHERE level = 2").fetchone()[0] == r["rarity"] and game.open_pack(c, 2) is None and game.open_pack(c, 9) is None
    assert game.summary(c)["packs"] == 1

# --- API ---
with TestClient(app) as cl:
    g = cl.get("/api/game").json()
    assert g["level"] >= 3 and any(p["level"] == 3 and not p["opened_at"] for p in g["packs_list"]) and g["missions"] and g["history"]
    j = cl.post("/api/packs/3/open").json(); assert j["reward"] in game.BY_LABEL and j["rarity"] in game.RARITY_WEIGHTS and j["icon"]
    assert cl.post("/api/packs/3/open").status_code == 404
    page = cl.get("/").text
    assert "/static/packfx.js" in page and "/static/packfx.css" in page
    assert cl.get("/static/packfx.js").status_code == 200 and "PackFX" in cl.get("/static/packfx.js").text
    assert any(p["opened_at"] and p["rarity"] and p["icon"] for p in cl.get("/api/game").json()["packs_list"]), "récompenses obtenues : rareté et icône"
    assert 'id="goals"' in page and "const GAME = " in page and 'data-view="objectifs"' in page
import random as _r
rng = _r.Random(0); seen = {}
with db.conn() as c:
    for lv in range(100, 400):
        c.execute("INSERT INTO packs (level) VALUES (?)", (lv,)); r = game.open_pack(c, lv, rng); seen[r["rarity"]] = seen.get(r["rarity"], 0) + 1
assert set(seen) == set(game.RARITY_WEIGHTS) and seen["common"] > seen["rare"] > seen["epic"] > seen["legendary"] > 0, seen   # rareté pondérée
print("OK jeu")
