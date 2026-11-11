import os, tempfile, sys, sqlite3, json
D = os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["SYNC_INTERVAL_MIN"] = "0"
os.environ["INVITE_CODE"] = "sesame"
os.environ.pop("AUTH_DISABLED", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
# ancienne installation mono-utilisateur à rattacher au premier compte
from app import db as _db
with sqlite3.connect(os.path.join(D, "devoirs.db")) as x:
    x.executescript(_db.SCHEMA)
    x.execute("INSERT INTO homework (id,subject,description,due_date) VALUES ('old','Maths','vieux devoir','2030-01-01')")
json.dump({"pronote_url": "https://x/pronote/mobile.parent.html"}, open(os.path.join(D, "credentials.json"), "w"))
from fastapi.testclient import TestClient
from app import db, qr as qrlogin, sync
from app.main import app

connects = []
qrlogin.decode_image = lambda data: {"url": "https://x/pronote/mobile.parent.html"}
def fake_connect(qr, pin):
    if pin != "1234": raise qrlogin.QRError("PIN refusé")
    connects.append(db.user_dir()); json.dump({"pronote_url": qr["url"], "who": db.user_dir()}, open(sync.creds_path(), "w")); return "X"
qrlogin.connect = fake_connect
sync.run_sync = lambda: None
H = {"Accept": "text/html"}
B64 = "data:image/png;base64,aGVsbG8="

def uid_of(login):
    from app import accounts
    return accounts._conn().execute("SELECT id FROM users WHERE login=?", (login,)).fetchone()[0]

def reg(c, login, pw="motdepasse1", invite="sesame", **kw):
    return c.post("/api/register", json={"login": login, "password": pw, "invite": invite, **kw})

with TestClient(app) as a, TestClient(app) as b:
    # non connecté : page → /login, API → 401, ressources PWA publiques
    r = a.get("/", headers=H, follow_redirects=False); assert r.status_code == 303 and r.headers["location"] == "/login"
    assert a.get("/api/homework").status_code == 401 and a.post("/api/reconnect", json={}).status_code == 401
    assert a.get("/login").status_code == 200 and a.get("/manifest.webmanifest").status_code == 200 and a.get("/sw.js").status_code == 200
    assert "Créer un compte" in a.get("/register").text and "rattachées" in a.get("/register").text
    # validations d'inscription
    assert reg(a, "alice", invite="faux").status_code == 403
    assert reg(a, "A!", ).status_code == 400 and reg(a, "alice", pw="court").status_code == 400
    r = reg(a, "alice", image=B64, pin="0000"); assert r.status_code == 400 and "PIN" in r.json()["detail"]
    assert db.LOCAL is False and not os.path.isdir(os.path.join(D, "users", "1")), "inscription ratée : rien ne doit rester"
    assert os.path.isfile(os.path.join(D, "devoirs.db")), "l'ancienne base ne doit pas être touchée par une inscription ratée"
    # 1er compte (QR facultatif car données existantes) : récupère l'ancienne installation
    r = reg(a, "Alice"); assert r.status_code == 201 and "session" in r.cookies, r.text
    assert not os.path.exists(os.path.join(D, "devoirs.db")) and os.path.isfile(os.path.join(D, "users", str(uid_of("alice")), "devoirs.db"))
    assert [h["subject"] for h in a.get("/api/homework").json()] == ["Maths"]
    assert "alice" in a.get("/", headers=H).text and 'data-account="alice"' in a.get("/", headers=H).text
    # 2e compte avec QR : QR obligatoire, base vide, jeton propre
    assert reg(b, "bob").status_code == 400
    assert reg(b, "alice", image=B64, pin="1234").status_code == 409
    r = reg(b, "bob", image=B64, pin="1234", child="Léa"); assert r.status_code == 201, r.text
    assert b.get("/api/homework").json() == []
    assert [h["subject"] for h in a.get("/api/homework").json()] == ["Maths"], "isolation des données"
    # écriture de l'un invisible pour l'autre
    assert b.post("/api/cards", json={"subject": "Perso", "description": "secret de bob", "due_date": "2030-02-02"}).status_code == 201
    assert "secret de bob" not in a.get("/api/homework").text and "secret de bob" in b.get("/api/homework").text
    assert b.put("/api/settings", json={"avatar": None, "theme": "dark"}).status_code == 200
    assert a.get("/api/settings").json()["theme"] == "auto"
    assert json.load(open(os.path.join(D, "users", str(uid_of("bob")), "credentials.json")))["who"].endswith("users/%d" % uid_of("bob"))
    assert 'Léa' in b.get("/", headers=H).text and "Léa" not in a.get("/", headers=H).text
    # connexion / déconnexion
    with TestClient(app) as c:
        assert c.post("/api/login", json={"login": "alice", "password": "faux"}).status_code == 401
        assert c.post("/api/login", json={"login": "inconnu", "password": "motdepasse1"}).status_code == 401
        r = c.post("/api/login", json={"login": "ALICE", "password": "motdepasse1"}); assert r.status_code == 200
        assert "HttpOnly" in r.headers["set-cookie"] and "samesite=lax" in r.headers["set-cookie"].lower()
        assert c.get("/api/homework").status_code == 200
        assert c.post("/logout").status_code == 200 and c.get("/api/homework").status_code == 401
    # cookie falsifié refusé
    a.cookies.set("session", "x"*40); assert a.get("/api/homework").status_code == 401
    # code d'invitation vide : inscriptions fermées une fois le premier compte créé
    os.environ["INVITE_CODE"] = ""
    with TestClient(app) as anon:
        assert reg(anon, "carl", invite="").status_code == 403 and "fermées" in anon.get("/register", headers=H).text
    # limitation de tentatives
    with TestClient(app) as c:
        codes = [c.post("/api/login", json={"login": "alice", "password": "faux"}).status_code for _ in range(10)]
        assert codes[-1] == 429, codes
print("OK comptes")
