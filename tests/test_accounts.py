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
qrlogin.decode_image = lambda data: {"url": "https://x/pronote/mobile.%s.html" % ("parent" if data.startswith(b"parent") else "eleve"), "v": data.decode()}
def fake_connect(qr, pin, role=None):
    if pin != "1234": raise qrlogin.QRError("PIN refusé")
    if role and qrlogin.qr_role(qr) != role: raise qrlogin.QRError("mauvais espace")
    import json as _j
    kids = {"parent": [{"id": "S1", "name": "Autre Nom", "class": "3A", "est": ""}],            # même identifiant
            "parent-nom": [{"id": "ZZ", "name": "Bob POLESE", "class": "3A", "est": ""}],        # autre id, même nom + classe
            "parent-aucun": [{"id": "Q", "name": "Inconnu Léo", "class": "3A", "est": ""}]}
    with db.conn() as c:
        vals = ({"pronote_children": _j.dumps(kids.get(qr["v"], kids["parent"]))} if role == "parent" else
                {"pronote_id": "S1", "pronote_name": "POLESE Bob", "pronote_class": "3A", "pronote_est": ""})
        vals["pronote_host"] = "x"
        c.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)", list(vals.items()))
    connects.append(db.user_dir()); json.dump({"pronote_url": qr["url"], "who": db.user_dir()}, open(sync.creds_path(), "w")); return "X"
qrlogin.connect = fake_connect
sync.run_sync = lambda: None
H = {"Accept": "text/html"}
B64 = "data:image/png;base64,aGVsbG8="
import base64 as _b
B64P = "data:image/png;base64," + _b.b64encode(b"parent").decode()
B64PN = "data:image/png;base64," + _b.b64encode(b"parent-nom").decode()
B64PX = "data:image/png;base64," + _b.b64encode(b"parent-aucun").decode()

def uid_of_or_none(login):
    from app import accounts
    r = accounts._conn().execute("SELECT id FROM users WHERE login=?", (login,)).fetchone()
    return r[0] if r else None

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
    assert reg(b, "bob", image=B64P, pin="1234").status_code == 400, "un élève ne s'inscrit pas avec un QR code parent"
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
    # ---- comptes parents : liaison par code, consultation seule ----
    code = b.post("/api/parent-invite").json()["code"]; assert len(code) == 9 and code[4] == "-"
    with TestClient(app) as p:
        # liaison automatique par les enfants du QR code parent (sans code)
        r = reg(p, "mamie", role="parent", image=B64PX, pin="1234"); assert r.status_code == 400 and "Inconnu Léo" in r.json()["detail"], r.text
        assert uid_of_or_none("mamie") is None, "inscription ratée : le compte parent ne doit pas rester"
        assert reg(p, "mamie", role="parent").status_code == 400, "sans code ni QR code"
        assert reg(p, "papa", role="parent", image=B64PN, pin="1234").status_code == 201       # niveau « nom + classe »
        assert [h["subject"] for h in p.get("/api/homework").json()] == ["Perso"] and 'data-readonly="1"' in p.get("/", headers=H).text
        p.post("/logout")
    with TestClient(app) as p:
        assert reg(p, "tonton", role="parent", image=B64P, pin="1234").status_code == 201      # niveau « id »
        assert [h["subject"] for h in p.get("/api/homework").json()] == ["Perso"]
        p.post("/logout")
    with TestClient(app) as p:
        assert reg(p, "maman", role="parent", link="FAUX-CODE", image=B64P, pin="1234").status_code == 403
        assert reg(p, "maman", role="parent", link=code, image=B64, pin="1234").status_code == 400, "parent : QR de l'espace élève refusé"
        assert reg(p, "maman", role="parent", link=code).status_code == 400, "QR obligatoire (sauf dev)"
        assert reg(p, "maman", role="parent", link=code.lower().replace("-", " "), image=B64P, pin="1234").status_code == 201
        assert [h["subject"] for h in p.get("/api/homework").json()] == ["Perso"], "le parent voit les données de l'élève lié (bob)"
        page = p.get("/", headers=H).text
        assert 'data-readonly="1"' in page and 'data-role="parent"' in page
        assert "data-child=" in page
        for method, url, kw in [("post", "/api/cards", {"json": {"subject": "x", "description": "y", "due_date": "2030-01-01"}}),
                                ("put", "/api/settings", {"json": {"theme": "dark"}}), ("post", "/sync", {}), ("post", "/api/reconnect", {"json": {}}),
                                ("post", "/api/parent-invite", {}), ("post", "/move/old", {}), ("post", "/api/packs/2/open", {}), ("post", "/api/grades/seen", {"json": {}}), ("post", "/api/missions/celebrated", {"json": {"ids": [1]}})]:
            assert getattr(p, method)(url, **kw).status_code == 403, url
        assert b.get("/api/settings").json()["theme"] == "dark" and len(b.get("/api/homework").json()) == 1
        assert reg(p, "papa", role="parent", link=code, image=B64P, pin="1234").status_code == 403, "code à usage unique"
        # le parent coche les récompenses remises (seule écriture permise), l'élève ne le peut pas
        with db.as_user(uid_of("bob")), db.conn() as c:
            from app import game as _g
            _g.load_examples(c); c.execute("INSERT OR IGNORE INTO packs (level) VALUES (2)"); _g.open_pack(c, 2)
            c.execute("INSERT OR IGNORE INTO packs (level) VALUES (3)")
        assert p.post("/api/packs/2/delivered", json={"delivered": True}).status_code == 200
        assert [x["delivered_at"] is not None for x in p.get("/api/game").json()["packs_list"] if x["level"] == 2] == [True]
        assert b.get("/api/game").json()["packs_list"][-1]["delivered_at"] is not None, "l'élève voit que la récompense est remise"
        # récompenses : le parent les définit (par rareté), l'élève ne peut ni les voir ni les modifier
        assert b.get("/api/rewards").status_code == 403 and b.post("/api/rewards", json={"label": "x", "rarity": "rare"}).status_code == 403
        n0 = len(p.get("/api/rewards").json()["rewards"])
        r = p.post("/api/rewards", json={"label": "Une glace", "rarity": "common", "icon": "🍦"}); assert r.status_code == 200
        rid = r.json()["id"]; assert any(x["id"] == rid and x["rarity"] == "common" for x in r.json()["rewards"]) and len(r.json()["rewards"]) == n0 + 1
        assert p.put(f"/api/rewards/{rid}", json={"label": "Deux glaces", "rarity": "rare", "icon": "🍨"}).json()["rewards"][-1]["label"] == "Deux glaces"
        assert p.post("/api/rewards", json={"label": "x", "rarity": "mythique"}).status_code == 422 and p.put("/api/rewards/99999", json={"label": "x", "rarity": "rare"}).status_code == 404
        assert p.delete(f"/api/rewards/{rid}").status_code == 200 and p.delete(f"/api/rewards/{rid}").status_code == 404
        assert len(p.get("/api/rewards").json()["rewards"]) == n0 and b.delete("/api/rewards/1").status_code == 403
        assert p.post("/api/packs/3/open").status_code == 403, "le parent n'ouvre pas les paquets"
        # bonus systématique (crédits) : défini par le parent, tiré à l'ouverture, remis séparément
        assert b.put("/api/rewards/bonus", json={"unit": "crédits", "rules": {}}).status_code == 403
        assert p.put("/api/rewards/bonus", json={"unit": "crédits", "rules": {"common": {"min": 2, "max": 2}, "rare": {"min": 1, "max": 1}, "epic": {"min": 3, "max": 3}, "legendary": {"min": 5, "max": 5}}}).status_code == 200
        r = p.put("/api/rewards/bonus", json={"unit": "", "rules": {"rare": {"min": 1, "max": 2}}}); assert r.status_code == 422 and "nom de la monnaie" in r.json()["detail"], r.text
        assert p.put("/api/rewards/bonus", json={"unit": "c", "rules": {"rare": {"min": 3, "max": 1}}}).status_code == 422
        assert p.get("/api/rewards").json()["bonus"]["unit"] == "crédits"
        with db.as_user(uid_of("bob")), db.conn() as c:
            c.execute("INSERT OR IGNORE INTO packs (level) VALUES (4)")
        j = b.post("/api/packs/4/open").json(); assert j["bonus"] and j["bonus"].split()[1].startswith("crédit"), j
        assert b.post("/api/packs/4/delivered", json={"delivered": True, "part": "bonus"}).status_code == 403
        assert p.post("/api/packs/4/delivered", json={"delivered": True, "part": "bonus"}).status_code == 200
        pk = next(x for x in p.get("/api/game").json()["packs_list"] if x["level"] == 4); assert pk["bonus_delivered_at"] and not pk["delivered_at"] and pk["bonus"] == j["bonus"]
        assert b.post("/api/packs/2/delivered", json={"delivered": False}).status_code == 403
        assert p.post("/api/packs/3/delivered", json={"delivered": True}).status_code == 404, "paquet non ouvert"
        assert p.post("/api/packs/2/delivered", json={"delivered": False}).status_code == 200
        assert p.post("/api/packs/2/open").status_code == 403, "le parent n'ouvre toujours pas de paquet"
        assert p.post("/logout").status_code == 200
    assert uid_of("maman") not in __import__("app.accounts", fromlist=["x"]).user_ids(), "la synchro ne concerne que les élèves"
    assert "maman" in b.post("/api/parent-invite").json()["parents"]
    # code d'invitation vide : inscriptions fermées une fois le premier compte créé
    os.environ["INVITE_CODE"] = ""
    with TestClient(app) as anon:
        assert reg(anon, "carl", invite="").status_code == 403 and "fermées" in anon.get("/register", headers=H).text
    # limitation de tentatives
    with TestClient(app) as c:
        codes = [c.post("/api/login", json={"login": "alice", "password": "faux"}).status_code for _ in range(10)]
        assert codes[-1] == 429, codes
# ---- compte administrateur : comme un élève, sans QR code, avec données de démo et outil de points ----
from app import admin as adm, accounts as acc
aid = adm.create_admin("Testeur", "motdepasse1")
try: adm.create_admin("testeur", "motdepasse1"); raise SystemExit("doublon accepté")
except ValueError: pass
assert aid not in acc.user_ids() and aid in acc.user_ids(("student", "admin")), "l'admin n'est jamais synchronisé"
import app.webauth as _w; _w._FAILS.clear()   # le test de limitation plus haut a bloqué cette adresse
with TestClient(app) as t:
    assert t.post("/api/login", json={"login": "testeur", "password": "motdepasse1"}).status_code == 200
    g = t.get("/api/game").json(); assert g["missions"] and g["history"], "données de démo + missions dès la première visite"
    assert t.get("/api/results").json()["periods"] and 'data-role="admin"' in t.get("/", headers=H).text
    r = t.post("/api/admin/points", json={"points": 25}); assert r.status_code == 200 and r.json()["points"] == g["points"] + 25
    g2 = t.get("/api/game").json(); assert g2["level"] > g["level"] and g2["packs"] >= 2
    assert t.post("/api/packs/%d/open" % g2["packs_list"][0]["level"]).status_code == 200
    assert t.post("/api/admin/points", json={"points": 0}).status_code == 422
    r = t.post("/api/admin/mission-done"); assert r.status_code == 200 and [m["label"] for m in r.json()["celebrate"]] == ["Mission de test"]
    assert t.post("/api/missions/celebrated", json={"ids": [m["id"] for m in r.json()["celebrate"]]}).json()["celebrate"] == []
    assert t.post("/api/reconnect", json={"image": "x", "pin": "1234"}).status_code == 403
    assert t.post("/sync", follow_redirects=False).status_code == 303
    with db.as_user(aid), db.conn() as c: assert c.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0] == 0
    code = t.post("/api/parent-invite").json()["code"]; assert len(code) == 9, "l'admin peut tester la liaison parent"
assert b.post("/api/admin/points", json={"points": 5}).status_code == 403, "réservé à l'admin"
assert b.post("/api/admin/mission-done").status_code == 403, "réservé à l'admin"
# passage d'un jeton parent à un jeton élève : un client élève n'a pas set_child
class StudentClient:
    logged_in = True
    info = type("I", (), {"id": "77", "name": "POLESE Lucie", "class_name": "3B", "establishment": "E"})()
    def export_credentials(self): return {"pronote_url": "https://x/pronote/mobile.eleve.html", "username": "u", "password": "p", "uuid": "z"}
class Factory:
    @staticmethod
    def token_login(**kw): return StudentClient()
real = sync.client_class; sync.client_class = lambda url: Factory
try:
    with db.as_user(uid_of("bob")):
        assert sync.child_name() == "Léa"   # ancien réglage « enfant » d'un compte parent
        assert isinstance(sync.get_client(), StudentClient)
        with db.conn() as c: st = dict(c.execute("SELECT key, value FROM settings").fetchall())
        assert st["pronote_id"] == "77" and st["pronote_host"] == "x", "l'identité est mémorisée dès la synchro, sans nouveau QR code"
finally: sync.client_class = real
# mémorisation de l'identité à partir d'objets pronotepy (élève : id ; parent : liste d'enfants)
from types import SimpleNamespace as NS
info = lambda i, n: NS(id=i, name=n, class_name="3A", establishment="Collège X")
with db.as_user(uid_of("bob")):
    qrlogin.remember_identity(NS(info=info("42", "POLESE Lucie")), "https://Pronote.Exemple.fr/pronote/mobile.eleve.html")
    with db.conn() as c: st = dict(c.execute("SELECT key, value FROM settings").fetchall())
    assert (st["pronote_id"], st["pronote_host"], st["pronote_class"], st["pronote_est"]) == ("42", "pronote.exemple.fr", "3A", "Collège X")
    qrlogin.remember_identity(NS(info=info("9", "M. Parent"), children=[info("42", "POLESE Lucie")]), "https://pronote.exemple.fr/p/mobile.parent.html")
    with db.conn() as c: st = dict(c.execute("SELECT key, value FROM settings").fetchall())
    assert json.loads(st["pronote_children"])[0]["id"] == "42"
print("OK comptes")
