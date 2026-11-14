"""Notes « pas encore vues » : historique initial vu, nouvelle note (même à date ancienne) non vue, marquage, migration, parent en lecture seule."""
import os, sys, tempfile
from datetime import date, timedelta
from types import SimpleNamespace as NS

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["AUTH_DISABLED"] = "1"
os.environ["SYNC_INTERVAL_MIN"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
from app import db, sync
from app.main import app

today = date.today()
def g(subj, d, val, avg="12"):
    return NS(subject=NS(name=subj), date=d, grade=val, out_of="20", coefficient="1", average=avg, max="19", comment=None)
class Client:
    def __init__(self, grades): self.periods = [NS(name="T1", start=today - timedelta(days=60), grades=grades)]

with TestClient(app) as c:
    first = [g("MATHS", today - timedelta(days=3), "17"), g("ANGLAIS", today - timedelta(days=9), "14")]
    sync._sync_grades(Client(first))
    gr = c.get("/api/grades/seen") if False else None
    page = c.get("/").text
    assert "const GRADES" in page and 'id="notes"' in page and "/static/notes.js" in page and 'id="nbadge"' in page
    js = c.get("/static/notes.js").text
    assert "Par matière" in js and "Chronologique" in js and "Toute l'année" in js, "vues chronologique / par matière, filtre par trimestre"
    with db.conn() as x:
        assert x.execute("SELECT COUNT(*) FROM grades WHERE seen_at IS NULL").fetchone()[0] == 0   # historique : déjà vu

    # une note arrive avec une date ANCIENNE : elle doit être non vue (la date ne suffit pas)
    old = g("FRANCAIS", today - timedelta(days=40), "18")
    sync._sync_grades(Client(first + [old]))
    with db.conn() as x:
        rows = x.execute("SELECT subject, seen_at FROM grades WHERE seen_at IS NULL").fetchall()
    assert [r["subject"] for r in rows] == ["FRANCAIS"], [dict(r) for r in rows]
    # une re-synchronisation ne remet pas à zéro l'état des autres notes
    sync._sync_grades(Client(first + [old]))
    with db.conn() as x:
        assert x.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 3 and x.execute("SELECT COUNT(*) FROM grades WHERE seen_at IS NULL").fetchone()[0] == 1
    from app.main import grades_data
    gd = grades_data()
    assert [x["subject"] for x in gd] == ["MATHS", "ANGLAIS", "FRANCAIS"] and [x["unseen"] for x in gd] == [0, 0, 1] and gd[2]["added"] == today.isoformat()
    # marquer vue
    ids = [x["id"] for x in gd if x["unseen"]]
    assert c.post("/api/grades/seen", json={"ids": ["inconnu"]}).json() == {"unseen": 1}
    assert c.post("/api/grades/seen", json={"ids": ids}).json() == {"unseen": 0}
    sync._sync_grades(Client(first + [old, g("SVT", today, "16")]))
    assert c.post("/api/grades/seen", json={}).json() == {"unseen": 0}   # toutes

    # migration : base ancienne sans colonne seen_at -> notes existantes considérées comme vues
    with db.conn() as x:
        x.executescript("DROP TABLE grades; CREATE TABLE grades (id TEXT PRIMARY KEY, period TEXT NOT NULL, subject TEXT NOT NULL, date TEXT NOT NULL, grade REAL NOT NULL, out_of REAL, coef REAL, class_avg REAL, max REAL, comment TEXT);"
                        "INSERT INTO grades VALUES ('a','T1','MATHS','2026-01-01',15,20,1,12,18,NULL);")
    db.init()
    with db.conn() as x:
        r = x.execute("SELECT seen_at FROM grades").fetchone()
    assert r["seen_at"] is not None
print("OK notes")
