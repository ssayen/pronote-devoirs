import os, tempfile, sys
from datetime import date, timedelta
from types import SimpleNamespace as NS
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["SYNC_INTERVAL_MIN"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
from app import sync, db
from app.main import app

calls = []
class HW:
    def __init__(s, i, d, done=False, files=()): s.id=i; s.subject=NS(name="Maths"); s.description=f"Ex {i}"; s.date=d; s.done=done; s.files=list(files)
    def set_done(s, v): calls.append((s.id, v)); s.done = v
class Broken:
    name = "casse.docx"; type = 1; url = "https://x/session-morte"
    @property
    def data(self): raise RuntimeError("session expirée")
hws = [HW("a", date.today()+timedelta(days=1), files=[
           NS(name="sujet é.pdf", type=1, url="https://x/session-liee", data=b"%PDF-contenu"),
           NS(name="https://exemple.fr/doc", type=0, url="https://exemple.fr/doc"), Broken()]),
       HW("b", date.today()-timedelta(days=2)), HW("c", date.today(), True)]
class C:
    def homework(self, a, b): return hws
sync.get_client = lambda: C()

# base héritée : le même devoir 3 fois sous des id Pronote différents (positions différentes)
db.init()
with db.conn() as x:
    for i, (st, ts) in enumerate([("todo", "2026-01-01"), ("doing", "2026-01-03"), ("todo", "2026-01-02")]):
        x.execute("INSERT INTO homework (id, subject, description, due_date, status, updated_at) VALUES (?,?,?,?,?,?)",
                  (f"147#old{i}", "Maths", "Ex b", (date.today()-timedelta(days=2)).isoformat(), st, ts))
db.init()
with db.conn() as x: assert [r["status"] for r in x.execute("SELECT * FROM homework")] == ["doing"]  # le plus récent gagne

def status():
    with db.conn() as x:
        return {r["description"][-1]: (r["status"], r["done"], r["pending_push"]) for r in x.execute("SELECT * FROM homework")}
def rid(n):
    with db.conn() as x: return x.execute("SELECT id FROM homework WHERE description = ?", (f"Ex {n}",)).fetchone()["id"]

with TestClient(app) as c:
    sync.run_sync()
    assert status() == {"a": ("todo", 0, 0), "b": ("doing", 0, 0), "c": ("done", 1, 0)}, status()  # b garde sa position
    A, B, Cc = rid("a"), rid("b"), rid("c")
    # Pronote change tous les id à chaque connexion : pas de doublons, positions conservées
    for h in hws: h.id = "nouvel-id-" + h.id
    sync.run_sync(); assert (A, B, Cc) == (rid("a"), rid("b"), rid("c")) and len(status()) == 3
    for h in hws: h.id = h.id.replace("nouvel-id-", "")
    c.post(f"/move/{B}", json={"status": "todo"})
    r = c.get("/"); assert r.status_code == 200 and "Ex a" in r.text and "sujet" in r.text
    # fichier Pronote téléchargé pendant la synchro puis servi par l'app ; lien externe conservé ; échec toléré
    assert "session-liee" not in r.text
    r = c.get(f"/file/{A}/0"); assert r.status_code == 200 and r.content == b"%PDF-contenu", r.status_code
    assert c.get(f"/file/{A}/1").status_code == 404 and c.get(f"/file/{A}/2").status_code == 404
    assert c.get(f"/file/{A}/9").status_code == 404 and c.get("/file/zzz/0").status_code == 404
    assert "https://exemple.fr/doc" in r.text or "https://exemple.fr/doc" in c.get("/").text

    # mode lecture (défaut) : déplacer ne pousse rien vers Pronote
    assert c.post(f"/move/{A}", json={"status": "doing"}).json()["push"] is False
    assert c.post(f"/move/{A}", json={"status": "done"}).json()["push"] is False
    sync.run_sync(); assert calls == [], calls
    assert status()["a"] == ("done", 1, 0)          # le choix local survit à la synchro
    assert c.post(f"/move/{A}", json={"status": "todo"}).status_code == 200

    # un statut inconnu ou un devoir inconnu est refusé
    assert c.post(f"/move/{A}", json={"status": "nawak"}).status_code == 422
    assert c.post("/move/zzz", json={"status": "todo"}).status_code == 404

    # changement fait côté Pronote : répercuté sur la colonne
    hws[1].done = True; sync.run_sync(); assert status()["b"][0] == "done"
    hws[1].done = False; sync.run_sync(); assert status()["b"][0] == "todo"
    # « en cours » ne bouge pas tant que Pronote ne change pas
    c.post(f"/move/{B}", json={"status": "doing"}); sync.run_sync(); assert status()["b"][0] == "doing"

    # écriture activée : passer à terminé / quitter terminé est envoyé, pas todo <-> doing
    os.environ["PUSH_TO_PRONOTE"] = "1"
    assert c.post(f"/move/{A}", json={"status": "doing"}).json()["push"] is False
    assert c.post(f"/move/{A}", json={"status": "done"}).json()["push"] is True
    assert calls == [("a", True)], calls
    assert status()["a"] == ("done", 1, 0)
    sync.run_sync(); assert calls == [("a", True)]   # pas de renvoi en double
    c.post(f"/move/{Cc}", json={"status": "todo"}); assert calls[-1] == ("c", False), calls
    assert status()["c"][0] == "todo"

    assert len(c.get("/api/homework").json()) == 3
    # « Nouveau » : rien à la 1re synchro ; un devoir apparu ensuite est marqué, et seulement lui
    with db.conn() as x: x.execute("UPDATE homework SET created_at = '2000-01-01 00:00:00'")  # la base de ce test n'était pas vide au départ
    assert not any(h["is_new"] for h in c.get("/api/homework").json())
    hws.append(HW("d", date.today()+timedelta(days=3))); sync.run_sync()
    api = {h["description"]: h["is_new"] for h in c.get("/api/homework").json()}
    assert api == {"Ex a": 0, "Ex b": 0, "Ex c": 0, "Ex d": 1}, api
    with db.conn() as x: x.execute("UPDATE homework SET created_at = datetime('now', '-49 hours') WHERE description='Ex d'")
    assert {h["description"]: h["is_new"] for h in c.get("/api/homework").json()}["Ex d"] == 0   # expire après 48 h

    # --- cartes personnelles (PUSH_TO_PRONOTE=1 ici : elles ne doivent jamais partir vers Pronote) ---
    n_calls = len(calls)
    r = c.post("/api/cards", json={"subject": " Maths ", "description": " Réviser le DS ", "due_date": (date.today()+timedelta(days=5)).isoformat()})
    assert r.status_code == 201, r.text
    m = r.json(); mid = m["id"]
    assert mid.startswith("local-") and m["subject"] == "Maths" and m["description"] == "Réviser le DS" and m["source"] == "local" and m["is_new"] == 0
    assert c.post("/api/cards", json={"description": "", "due_date": "2026-12-01"}).status_code == 422       # texte vide
    assert c.post("/api/cards", json={"description": "x", "due_date": "pas-une-date"}).status_code == 422
    assert c.post("/api/cards", json={"description": "x", "due_date": "2026-12-01", "status": "nawak"}).status_code == 422
    assert c.post("/api/cards", json={"description": "x", "due_date": "2026-12-01", "subject": "y"*61}).status_code == 422
    assert c.post("/api/cards", json={"description": "sans matière", "due_date": "2026-12-01", "subject": "  "}).json()["subject"] == "Perso"
    # mise à jour, déplacement : jamais d'envoi vers Pronote
    r = c.put(f"/api/cards/{mid}", json={"subject": "Maths", "description": "Réviser le DS p. 40", "due_date": "2026-12-24", "status": "doing"})
    assert r.status_code == 200 and r.json()["description"].endswith("p. 40") and r.json()["status"] == "doing"
    assert c.post(f"/move/{mid}", json={"status": "done"}).json()["push"] is False
    assert c.put(f"/api/cards/{mid}", json={"description": "fini", "due_date": "2026-12-24", "status": "done"}).json()["done"] == 1
    sync.run_sync(); assert len(calls) == n_calls, calls[n_calls:]
    got = [h for h in c.get("/api/homework").json() if h["id"] == mid]
    assert got and got[0]["description"] == "fini" and got[0]["status"] == "done"            # survit à la synchro
    # les cartes Pronote ne sont ni modifiables ni supprimables ; inconnues -> 404
    body = {"description": "x", "due_date": "2026-12-01"}
    assert c.put(f"/api/cards/{A}", json=body).status_code == 403 and c.delete(f"/api/cards/{A}").status_code == 403
    assert c.put("/api/cards/zzz", json=body).status_code == 404 and c.delete("/api/cards/zzz").status_code == 404
    assert c.delete(f"/api/cards/{mid}").status_code == 204
    assert all(h["id"] != mid for h in c.get("/api/homework").json())
    assert "Ex a" in c.get("/").text
    print("OK")
