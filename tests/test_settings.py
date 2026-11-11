"""Personnalisation : avatar choisi, validé, persistant (redémarrage), jamais un identifiant inconnu."""
import os, sys, tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["AUTH_DISABLED"] = "1"
os.environ["SYNC_INTERVAL_MIN"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
from app import db
from app.main import app, avatar_list

ids = [a["id"] for a in avatar_list()]
assert len(ids) >= 3, "avatars web manquants (python scripts/build_avatars.py)"

with TestClient(app) as c:
    assert c.get("/api/settings").json() == {"avatar": None, "theme": "auto"}
    page = c.get("/").text
    assert 'id="avatar"' in page and 'id="v-perso"' in page and 'id="avatar-menu"' in page and "/static/perso.js" in page and "const AVATARS" in page

    r = c.put("/api/settings", json={"avatar": ids[2]})
    assert r.status_code == 200 and r.json() == {"avatar": ids[2], "theme": "auto"}
    assert c.get("/api/settings").json() == {"avatar": ids[2], "theme": "auto"}
    assert f'"avatar": "{ids[2]}"' in c.get("/").text.replace('"avatar":"', '"avatar": "')   # injecté dans la page
    assert c.get(f"/static/avatars/{ids[2]}.jpg").status_code == 200

    # identifiant inconnu ou malveillant : refusé, le choix précédent est conservé
    for bad in ("nimporte-quoi", "../../etc/passwd", "", "x" * 200):
        assert c.put("/api/settings", json={"avatar": bad}).status_code in (422,), bad
    assert c.get("/api/settings").json() == {"avatar": ids[2], "theme": "auto"}

    # changer, puis retirer
    assert c.put("/api/settings", json={"avatar": ids[0]}).json() == {"avatar": ids[0], "theme": "auto"}
    with db.conn() as x: assert x.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 1   # pas de doublon
    assert c.put("/api/settings", json={"avatar": None}).json() == {"avatar": None, "theme": "auto"}

    c.put("/api/settings", json={"avatar": ids[1]})

    # thème : modification partielle (n'écrase pas l'avatar), posé côté serveur dans le HTML, validé
    assert 'data-theme' not in c.get("/").text.split(">", 3)[2]
    assert c.put("/api/settings", json={"theme": "dark"}).json() == {"avatar": ids[1], "theme": "dark"}
    assert '<html lang="fr" data-theme="dark">' in c.get("/").text
    assert c.put("/api/settings", json={"avatar": ids[0]}).json() == {"avatar": ids[0], "theme": "dark"}   # l'avatar ne touche pas au thème
    assert c.put("/api/settings", json={"theme": "light"}).json()["theme"] == "light"
    for bad in ("violet", "", "DARK"):
        assert c.put("/api/settings", json={"theme": bad}).status_code == 422, bad
    assert c.put("/api/settings", json={"theme": "auto"}).json() == {"avatar": ids[0], "theme": "auto"}
    assert "data-theme" not in c.get("/").text.split("<head>")[0]
    c.put("/api/settings", json={"avatar": ids[1], "theme": "dark"})

# « redémarrage » : nouvelle instance de l'application sur le même dossier de données
with TestClient(app) as c2:
    assert c2.get("/api/settings").json() == {"avatar": ids[1], "theme": "dark"}
    # un avatar qui n'existe plus (image supprimée) n'est pas renvoyé
    with db.conn() as x: x.execute("UPDATE settings SET value = 'disparu' WHERE key = 'avatar'")
    assert c2.get("/api/settings").json() == {"avatar": None, "theme": "dark"}
print("OK")
