"""Remise à plat des objectifs d'un élève : simulation sans écriture, application avec sauvegarde, points sans doublon."""
import glob, io, os, sys, tempfile
from contextlib import redirect_stdout
from datetime import date, timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ.pop("AUTH_DISABLED", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app import accounts, db, game, reset_game

accounts.init()
uid = accounts.create("lucie", "motdepasse1", "student")
iso = lambda n: (date.today() - timedelta(days=n)).isoformat()
with db.as_user(uid):
    db.init()
    with db.conn() as c:
        c.execute("INSERT INTO periods (name, position, overall, class_overall) VALUES ('T1', 0, 14.3, 12.5)")
        for s, st, cl in (("MATHS", 13.6, 11.0), ("SVT", 18.0, 13.0), ("ARTS", 12.0, 14.5), ("ANGLAIS", 15.0, 13.0)):
            c.execute("INSERT INTO averages VALUES ('T1', ?, ?, ?, 3, 19)", (s, st, cl))
        for i, (d, g) in enumerate(((iso(80), 19), (iso(60), 17), (iso(40), 20), (iso(5), 18), (iso(3), 12))):   # 2026-09-29 simulé : iso(50)
            c.execute("INSERT INTO grades (id, period, subject, date, grade, out_of, coef, class_avg, max, first_seen, seen_at) VALUES (?,?,?,?,?,20,1,12,19,datetime('now'),datetime('now'))",
                      (f"g{i}", "T1", "MATHS", d, g))
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('game_since', ?)", (iso(10),))   # activation récente : l'historique n'a pas été compté
        c.execute("INSERT INTO missions (kind, params, baseline, points, label, started_at, expires_at) VALUES ('avg_up','{\"delta\":1}','{\"avg\":13,\"period\":\"T1\"}',2,'ancien format',?,?)", (iso(5), iso(-16)))
        game.update(c)
        before_pts = game.total_points(c)
    after = iso(50)   # notes à partir de iso(49) : 17 -> non (iso(60)), 20 (iso(40)), 18 (iso(5)), 12 (iso(3))

    def run(*extra):
        buf = io.StringIO()
        with redirect_stdout(buf): rc = reset_game.main(["lucie", "--after", after, *extra])
        return rc, buf.getvalue()

    # simulation : rien ne change
    rc, out = run()
    assert rc == 0 and "SIMULATION" in out
    if os.environ.get("SHOW"): print(out)
    with db.conn() as c:
        assert game.total_points(c) == before_pts and c.execute("SELECT label FROM missions WHERE status='active'").fetchone()[0] == "ancien format"
        assert c.execute("SELECT COUNT(*) FROM grades WHERE seen_at IS NULL").fetchone()[0] == 0
    assert not glob.glob(os.path.join(db.user_dir(), "devoirs.db.avant-reset-*"))

    # application
    rc, out = run("--apply")
    assert rc == 0 and "APPLIQUÉ" in out and "Sauvegarde" in out, out
    assert len(glob.glob(os.path.join(db.user_dir(), "devoirs.db.avant-reset-*"))) == 1
    with db.conn() as c:
        assert game.total_points(c) == before_pts + 3, (game.total_points(c), before_pts)        # +3 : la note de 20 (iso(40)) ; 18 déjà comptée
        assert c.execute("SELECT COUNT(*) FROM grades WHERE seen_at IS NULL").fetchone()[0] == 3   # notes après la date : iso(40), iso(5), iso(3)
        ms = c.execute("SELECT label FROM missions WHERE status = 'active'").fetchall()
        assert len(ms) == 3 and "ancien format" not in [m[0] for m in ms]
        assert game._setting(c, "game_since") == (date.fromisoformat(after) + timedelta(days=1)).isoformat()
    # une seconde application ne recompte rien
    run("--apply")
    with db.conn() as c:
        assert game.total_points(c) == before_pts + 3
    assert reset_game.main(["inconnue", "--after", after]) == 1
print("OK reset")
