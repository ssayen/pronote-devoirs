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
    cel = game.summary(c)["celebrate"]                                              # mission réussie : à célébrer à la prochaine ouverture
    assert [x["id"] for x in cel] == [m["id"]] and cel[0]["points"] == 2, cel
    game.mark_celebrated(c, [m["id"]]); assert game.summary(c)["celebrate"] == []   # une seule fois
    game.mark_celebrated(c, [m["id"]]); assert game.summary(c)["celebrate"] == []

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

    # --- barèmes ---
    c.execute("UPDATE periods SET overall = 13.0 WHERE name = 'Trimestre 1'")
    c.execute("UPDATE averages SET student = 12.0 WHERE subject = 'MATHEMATIQUES'")   # remet l'état de départ
    cands = game._candidates(c)
    pts = lambda kind, pred=lambda m: True: sorted(m["points"] for m in cands if m["kind"] == kind and pred(m))
    maths = lambda: sorted((m["params"]["target"], m["points"]) for m in game._candidates(c) if m["kind"] == "avg_up" and m["subject"] == "MATHEMATIQUES")
    assert maths() == [(13, 2), (14, 4), (15, 6)], maths()                       # 12,0 : cibles rondes, points selon l'écart
    c.execute("UPDATE averages SET student = 13.4 WHERE subject = 'MATHEMATIQUES'")
    assert maths() == [(14, 2), (15, 4), (16, 6)], maths()                       # 13,4 : 14, 15, 16
    c.execute("UPDATE averages SET student = 13.9 WHERE subject = 'MATHEMATIQUES'")
    assert maths()[0][0] == 15, "écart de 0,1 : on ne propose pas 14"
    # priorité aux moyennes basses : 13,6 -> 15 doit sortir bien plus souvent que 18 -> 19
    c.execute("UPDATE averages SET student = 13.6 WHERE subject = 'MATHEMATIQUES'"); c.execute("UPDATE averages SET student = 18 WHERE subject = 'SVT'")
    import random as _rd
    wl = {(m["subject"], m["params"]["target"]): m["weight"] for m in game._candidates(c) if m["kind"] == "avg_up"}
    assert wl[("MATHEMATIQUES", 15)] > 4 * wl[("SVT", 19)], wl
    cnt = {"MATHEMATIQUES": 0, "SVT": 0}; r0 = _rd.Random(1)
    pool = [m for m in game._candidates(c) if m["kind"] == "avg_up" and m["subject"] in cnt]
    for _ in range(600): cnt[r0.choices(pool, weights=[m["weight"] for m in pool])[0]["subject"]] += 1
    assert cnt["MATHEMATIQUES"] > 4 * cnt["SVT"], cnt
    c.execute("UPDATE averages SET student = 15.0 WHERE subject = 'SVT'")
    c.execute("UPDATE averages SET student = 12.0 WHERE subject = 'MATHEMATIQUES'")
    mm = {"params": json.dumps({"target": 14}), "baseline": json.dumps({"avg": 13.4, "period": "Trimestre 1"}), "kind": "avg_up", "subject": "MATHEMATIQUES"}
    assert game.progress(c, mm)["done"] is False                                  # moyenne actuelle 12,0 < 14
    c.execute("UPDATE averages SET student = 14.0 WHERE subject = 'MATHEMATIQUES'")
    assert game.progress(c, mm)["done"] is True and "objectif 14" in game.progress(c, mm)["text"]
    c.execute("UPDATE averages SET student = 12.0 WHERE subject = 'MATHEMATIQUES'")
    assert "Atteindre 14 de moyenne en Mathematiques" in [m["label"] for m in game._candidates(c)]
    assert pts("beat_class", lambda m: m["subject"] == "ARTS") == [2], "écart 0,5 : 2 pts"
    assert pts("beat_class", lambda m: m["subject"] == "ANGLAIS") == [5], "écart 2,5 : 5 pts"
    assert pts("overall_up") == [5, 10], pts("overall_up")           # 13,0 : 13,5 puis 14
    ov = lambda: sorted((m["params"]["target"], m["points"]) for m in game._candidates(c) if m["kind"] == "overall_up")
    c.execute("UPDATE periods SET overall = 14.3 WHERE name = 'Trimestre 1'")
    assert ov() == [(14.5, 2), (15, 7)], ov()
    assert "Atteindre 14,5 de moyenne générale" in [m["label"] for m in game._candidates(c)]
    c.execute("UPDATE periods SET overall = 13.0 WHERE name = 'Trimestre 1'")
    assert pts("above_class") == [1, 3] and pts("above_class") == [1, 3] and pts("good_grades") == [2, 5, 10]
    assert {m["points"] for m in cands if m["kind"] == "beat_class"} <= {2, 4, 5}
    c.execute("UPDATE averages SET student = 11.0, class_avg = 12.5 WHERE subject = 'ARTS'")   # écart 1,5 : 4 pts
    assert [m["points"] for m in game._candidates(c) if m["kind"] == "beat_class" and m["subject"] == "ARTS"] == [4]
    c.execute("UPDATE averages SET student = 14.0, class_avg = 14.5 WHERE subject = 'ARTS'")
    for _ in range(40):   # le tirage commence par le type : les 5 types apparaissent, jamais deux fois le même d'emblée
        c.execute("DELETE FROM missions"); game.generate(c)
        ks = [r[0] for r in c.execute("SELECT kind FROM missions")]; assert len(ks) == 3 and len(set(ks)) == 3, ks
        seen_kinds = globals().setdefault("seen_kinds", set()); seen_kinds.update(ks)
    assert seen_kinds == {"avg_up", "beat_class", "overall_up", "above_class", "good_grades"}, seen_kinds

    # moyenne générale
    c.execute("DELETE FROM missions")
    c.execute("INSERT INTO missions (kind, params, baseline, points, label, started_at, expires_at) VALUES ('overall_up',?,?,2,'+0,2 générale',?,?)",
              (json.dumps({"delta": 0.2}), json.dumps({"avg": 13.0, "period": "Trimestre 1"}), iso(5), iso(-10)))
    m = c.execute("SELECT * FROM missions").fetchone(); assert game.progress(c, m)["done"] is False
    c.execute("UPDATE periods SET overall = 13.1 WHERE name = 'Trimestre 1'"); assert game.progress(c, m)["done"] is False
    c.execute("UPDATE periods SET overall = 13.2 WHERE name = 'Trimestre 1'"); assert game.progress(c, m)["done"] is True

    # notes au-dessus de la moyenne de la classe : note > moyenne de l'épreuve, notes postérieures au début, moyenne connue
    c.execute("DELETE FROM missions")
    c.execute("INSERT INTO missions (kind, params, baseline, points, label, started_at, expires_at) VALUES ('above_class',?,'{}',1,'2 notes > classe',?,?)",
              (json.dumps({"n": 2}), iso(0), iso(-10)))
    m = c.execute("SELECT * FROM missions").fetchone()
    for i, (g, cl, d) in enumerate([(15, 12, iso(0)), (12, 12, iso(0)), (9, 12, iso(0)), (16, None, iso(0)), (18, 10, iso(3))]):
        c.execute("INSERT INTO grades (id, period, subject, date, grade, class_avg) VALUES (?, 'T1', 'X', ?, ?, ?)", (f"ac{i}", d, g, cl))
    assert game.progress(c, m)["current"] == 1, "seule la note 15 > 12 compte (égalité, sous la moyenne, sans moyenne et antérieure exclues)"
    c.execute("INSERT INTO grades (id, period, subject, date, grade, class_avg) VALUES ('ac9', 'T1', 'X', ?, 14, 11)", (iso(0),))
    assert game.progress(c, m)["done"] is True

    # --- sans récompense définie : pas de paquet, le niveau est seulement célébré (animation) ---
    c.execute("DELETE FROM points"); c.execute("DELETE FROM packs"); c.execute("DELETE FROM levelups"); c.execute("DELETE FROM settings WHERE key = 'level_seen'")
    game.ensure_packs(c)                                                          # premier passage : niveau actuel (1) mémorisé, rien de rétroactif
    game.award(c, "mission", "t0", 12, "test"); game.ensure_packs(c); game.ensure_packs(c)
    assert c.execute("SELECT COUNT(*) FROM packs").fetchone()[0] == 0 and game.summary(c)["levelup"] == [2] and game.summary(c)["has_rewards"] is False
    try: c.execute("INSERT INTO packs (level) VALUES (50)"); game.open_pack(c, 50); raise SystemExit("ouverture sans récompense acceptée")
    except game.NoRewards: pass
    c.execute("DELETE FROM packs WHERE level = 50")
    game.mark_celebrated(c, [], [2]); assert game.summary(c)["levelup"] == []
    # --- avec récompenses : un paquet par niveau, ouvert une seule fois ---
    game.load_examples(c); assert game.load_examples(c) == 0, "les exemples ne se chargent qu'une fois"
    c.execute("DELETE FROM points"); game.award(c, "mission", "t1", 25, "test"); c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('level_seen', '1')")
    game.ensure_packs(c); game.ensure_packs(c)
    assert [r[0] for r in c.execute("SELECT level FROM packs ORDER BY level")] == [2, 3]
    r = game.open_pack(c, 2); assert r["label"] in {x["label"] for x in game.EXAMPLE_REWARDS} and c.execute("SELECT rarity FROM packs WHERE level = 2").fetchone()[0] == r["rarity"] and game.open_pack(c, 2) is None and game.open_pack(c, 9) is None
    assert game.summary(c)["packs"] == 1

# --- API ---
with TestClient(app) as cl:
    g = cl.get("/api/game").json()
    with db.conn() as x:
        x.execute("INSERT INTO missions (kind, params, baseline, points, label, started_at, expires_at, status, done_at) VALUES ('good_grades','{}','{}',5,'fête',?,?,'done',?)", (iso(3), iso(-10), iso(0)))
        mid = x.execute("SELECT id FROM missions WHERE label = 'fête'").fetchone()[0]
    cel = [m["label"] for m in cl.get("/api/game").json()["celebrate"]]
    assert "fête" in cel and "celebrate" in cl.get("/").text, cel
    ids = [m["id"] for m in cl.get("/api/game").json()["celebrate"]]
    assert cl.post("/api/missions/celebrated", json={"ids": ids}).json()["celebrate"] == [] and cl.get("/api/game").json()["celebrate"] == []
    assert g["level"] >= 3 and any(p["level"] == 3 and not p["opened_at"] for p in g["packs_list"]) and g["missions"] and g["history"]
    j = cl.post("/api/packs/3/open").json(); assert j["reward"] in {x["label"] for x in game.EXAMPLE_REWARDS} and j["rarity"] in game.RARITY_WEIGHTS and j["icon"]
    assert cl.post("/api/packs/3/open").status_code == 404
    assert cl.post("/api/packs/3/delivered", json={"delivered": True}).status_code == 200
    assert next(x for x in cl.get("/api/game").json()["packs_list"] if x["level"] == 3)["delivered_at"]
    assert cl.post("/api/packs/3/delivered", json={"delivered": False}).status_code == 200
    assert next(x for x in cl.get("/api/game").json()["packs_list"] if x["level"] == 3)["delivered_at"] is None
    assert cl.post("/api/packs/99/delivered", json={"delivered": True}).status_code == 404
    page = cl.get("/").text
    assert "/static/packfx.js" in page and "/static/packfx.css" in page
    assert cl.get("/static/packfx.js").status_code == 200 and "PackFX" in cl.get("/static/packfx.js").text
    assert any(p["opened_at"] and p["rarity"] and p["icon"] for p in cl.get("/api/game").json()["packs_list"]), "récompenses obtenues : rareté et icône"
    import re
    assert not re.search(r"\.avwrap \.lvl \{[^}]*pointer-events:\s*none", page), "la pastille de niveau doit rester cliquable"
    assert 'id="goals"' in page and "const GAME = " in page and 'data-view="objectifs"' in page
import random as _r
rng = _r.Random(0); seen = {}
with db.conn() as c:
    c.execute("DELETE FROM rewards"); game.load_examples(c)
    for lv in range(100, 400):
        c.execute("INSERT INTO packs (level) VALUES (?)", (lv,)); r = game.open_pack(c, lv, rng); seen[r["rarity"]] = seen.get(r["rarity"], 0) + 1
assert set(seen) == set(game.RARITY_WEIGHTS) and seen["common"] > seen["rare"] > seen["epic"] > seen["legendary"] > 0, seen   # rareté pondérée
# raretés sans récompense : jamais tirées ; une seule rareté définie : toujours celle-là
with db.conn() as c:
    c.execute("DELETE FROM rewards WHERE rarity != 'rare'")
    got = set()
    for lv in range(500, 540):
        c.execute("INSERT INTO packs (level) VALUES (?)", (lv,)); got.add(game.open_pack(c, lv, rng)["rarity"])
    assert got == {"rare"}, got
    # validations
    for bad in (("", "rare", ""), ("x", "mythique", ""), ("x" * 81, "rare", ""), ("x", "rare", "123456789")):
        try: game.add_reward(c, *bad); raise SystemExit(f"récompense invalide acceptée : {bad}")
        except ValueError: pass
# bonus systématique : nombre tiré entre min et max, unité, singulier / pluriel, remise séparée
assert game.bonus_text(1, "crédits") == "1 crédit" and game.bonus_text(3, "crédits") == "3 crédits" and game.bonus_text(2, "jeton") == "2 jeton"
with db.conn() as c:
    game.set_bonus(c, "crédits", {"rare": {"min": 1, "max": 3}, "common": None})
    assert game.bonus_config(c) == {"unit": "crédits", "rules": {"rare": {"min": 1, "max": 3}}}
    vals = set()
    for lv in range(600, 660):
        c.execute("INSERT INTO packs (level) VALUES (?)", (lv,)); r = game.open_pack(c, lv, rng); vals.add(r["bonus_n"])
        assert r["bonus"] == game.bonus_text(r["bonus_n"], "crédits")
    assert vals == {1, 2, 3}, vals
    assert c.execute("SELECT bonus_n, bonus_unit FROM packs WHERE level = 600").fetchone()[1] == "crédits"
    assert game.set_delivered(c, 600, True, "bonus") and c.execute("SELECT bonus_delivered_at, delivered_at FROM packs WHERE level = 600").fetchone()[0] and c.execute("SELECT delivered_at FROM packs WHERE level = 600").fetchone()[0] is None
    assert game.set_delivered(c, 600, False, "bonus")
    # pas de bonus pour une rareté sans règle ; pas de remise « bonus » s'il n'y en a pas
    game.set_bonus(c, "crédits", {}); c.execute("INSERT INTO packs (level) VALUES (700)"); r = game.open_pack(c, 700, rng)
    assert r["bonus"] is None and not game.set_delivered(c, 700, True, "bonus")
    for bad in (("", {"rare": {"min": 1, "max": 3}}), ("x" * 21, {}), ("c", {"rare": {"min": 3, "max": 1}}), ("c", {"rare": {"min": 0, "max": 0}}), ("c", {"mythique": {"min": 1, "max": 2}}), ("c", {"rare": {"min": 1, "max": 101}})):
        try: game.set_bonus(c, *bad); raise SystemExit(f"bonus invalide accepté : {bad}")
        except ValueError: pass
print("OK jeu")
