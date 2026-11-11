"""Moyennes : lecture depuis Pronote (faux client), conversion sur 20, valeurs non numériques, API et page."""
import os, sys, tempfile
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["AUTH_DISABLED"] = "1"
os.environ["SYNC_INTERVAL_MIN"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
from app import db, sync
from app.main import app

assert sync._num("14,5") == 14.5 and sync._num("Abs") is None and sync._num("") is None
assert sync._num("15", "30") == 10.0 and sync._num("8", "10") == 16.0

def avg(name, st, cl, lo, hi, out="20"):
    return NS(subject=NS(name=name), student=st, class_average=cl, min=lo, max=hi, out_of=out)

class P:
    def __init__(self, name, start, avgs, overall="14,2", cls="12,5"):
        self.name, self.start, self.end = name, start, start + timedelta(days=90)
        self._a, self.overall_average, self.class_overall_average = avgs, overall, cls
    @property
    def averages(self): return self._a

today = datetime.combine(date.today(), datetime.min.time())
class Client:
    periods = [P("Trimestre 1", today - timedelta(days=100), [avg("MATHS", "16,5", "11,2", "3", "19"), avg("ANGLAIS", "Abs", "13", "7", "19"), avg("SPORT", "15", "13", "8", "18", "30")]),
               P("Trimestre 2", today - timedelta(days=5), [avg("MATHS", "17", "11", "3", "19")]),
               P("Trimestre 3", today + timedelta(days=80), [avg("MATHS", "1", "1", "1", "1")])]  # pas commencé : ignoré
    def homework(self, a, b): return []
sync.get_client = lambda: Client()

with TestClient(app) as c:
    sync.run_sync()
    with db.conn() as x: msg = x.execute("SELECT message FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert "2 période(s)" in msg, msg
    r = c.get("/api/results").json()["periods"]
    assert [p["name"] for p in r] == ["Trimestre 1", "Trimestre 2"], r
    t1 = {s["subject"]: s for s in r[0]["subjects"]}
    assert t1["MATHS"]["student"] == 16.5 and t1["MATHS"]["class_avg"] == 11.2
    assert t1["ANGLAIS"]["student"] is None and t1["ANGLAIS"]["class_avg"] == 13.0   # « Abs » : pas de valeur
    assert t1["SPORT"]["student"] == 10.0                                             # 15/30 -> 10/20
    assert r[0]["overall"] == 14.2 and r[0]["class_overall"] == 12.5
    # une relecture n'invente rien et une période vide ne vide pas l'existant
    Client.periods[1]._a = []; sync.run_sync()
    assert len(c.get("/api/results").json()["periods"][1]["subjects"]) == 1
    page = c.get("/").text
    assert 'id="results"' in page and "/static/results.js" in page and "const RESULTS" in page
    assert c.get("/static/results.js").status_code == 200
print("OK")
