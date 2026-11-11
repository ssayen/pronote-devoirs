"""Emploi du temps : lecture depuis Pronote (faux client), remplacement de la fenêtre, API et page."""
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

mon = datetime.combine(date.today() - timedelta(days=date.today().weekday()), datetime.min.time())
def at(day, h, m=0): return mon + timedelta(days=day, hours=h, minutes=m)
def les(day, h, subject, canceled=False, room="204", status=None, test=False, dur=1):
    return NS(subject=NS(name=subject) if subject else None, start=at(day, h), end=at(day, h + dur), teacher_name="M. DUPONT",
              classroom=room, status=status, canceled=canceled, test=test, detention=False, outing=False, memo=None)

state = {"lessons": [les(0, 8, "MATHEMATIQUES"), les(0, 9, "FRANCAIS", canceled=True, status="Prof. absent"),
                     les(1, 8, "ANGLAIS", test=True), les(1, 8, "ITALIEN"), les(2, 10, None)]}
asked = []
class Client:
    periods = []
    def homework(self, a, b): return []
    def lessons(self, lo, hi): asked.append((lo, hi)); return state["lessons"]
sync.get_client = lambda: Client()

with TestClient(app) as c:
    sync.run_sync()
    with db.conn() as x: msg = x.execute("SELECT message FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert "5 cours" in msg, msg
    lo, hi = asked[-1]
    assert lo == (mon - timedelta(days=7)).date() and hi == (mon + timedelta(days=35)).date(), asked
    rows = c.get("/api/lessons").json()
    assert len(rows) == 5, rows                                     # deux cours simultanés conservés tous les deux
    by = {r["subject"]: r for r in rows}
    assert by["FRANCAIS"]["canceled"] == 1 and by["FRANCAIS"]["status"] == "Prof. absent"
    assert by["ANGLAIS"]["test"] == 1 and by["MATHEMATIQUES"]["room"] == "204"
    assert by["Cours"]["start"] == at(2, 10).strftime("%Y-%m-%dT%H:%M")  # matière absente : libellé par défaut

    # relecture : un cours supprimé disparaît, un cours modifié est mis à jour, pas de doublon
    state["lessons"] = [les(0, 8, "MATHEMATIQUES", room="305"), les(1, 8, "ANGLAIS")]
    sync.run_sync()
    rows = c.get("/api/lessons").json()
    assert sorted(r["subject"] for r in rows) == ["ANGLAIS", "MATHEMATIQUES"], rows
    assert [r["room"] for r in rows if r["subject"] == "MATHEMATIQUES"] == ["305"]

    # l'historique plus ancien que la fenêtre n'est pas touché
    with db.conn() as x:
        old = (mon - timedelta(days=30)).strftime("%Y-%m-%dT08:00")
        x.execute("INSERT INTO lessons (id, start, end, subject) VALUES ('old', ?, ?, 'VIEUX')", (old, old))
    sync.run_sync()
    assert any(r["subject"] == "VIEUX" for r in c.get("/api/lessons").json())

    # un échec de lecture de l'emploi du temps ne casse pas la synchro des devoirs
    Client.lessons = lambda self, a, b: (_ for _ in ()).throw(ConnectionError("réseau"))
    sync.run_sync()
    with db.conn() as x: last = x.execute("SELECT kind, message FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
    assert last["kind"] == "ok" and "emploi du temps non lu" in last["message"], dict(last)
    assert len(c.get("/api/lessons").json()) == 3                    # données précédentes conservées

    page = c.get("/").text
    assert 'id="timetable"' in page and "/static/timetable.js" in page and "const LESSONS" in page and "initViews()" in page
    for f in ("timetable.js", "views.js", "results.js"): assert c.get("/static/" + f).status_code == 200
print("OK")
