"""Jeton Pronote expiré : bannière, notification une seule fois par changement d'état, reconnexion."""
import json, os, sqlite3, sys, tempfile, threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace as NS

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["SYNC_INTERVAL_MIN"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# --- migration : un ancien journal sans colonne « kind » ---
with sqlite3.connect(os.path.join(os.environ["DATA_DIR"], "devoirs.db")) as x:
    x.executescript("""CREATE TABLE sync_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL DEFAULT (datetime('now')),
                       ok INTEGER NOT NULL, message TEXT NOT NULL);
                       INSERT INTO sync_log (ok, message) VALUES (1, 'vieux ok'), (0, 'vieille erreur');""")

from fastapi.testclient import TestClient
from app import db, sync
from app.main import app

# --- faux serveur de notification (ntfy-like) ---
received = []
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        received.append({"path": self.path, "title": self.headers.get("Title"), "auth": self.headers.get("Authorization"),
                         "body": self.rfile.read(int(self.headers["Content-Length"])).decode()})
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_port}/mon-topic"

def log():
    with db.conn() as c: return [(r["kind"], r["ok"]) for r in c.execute("SELECT * FROM sync_log ORDER BY id")]

state = {"mode": "ok"}
class Client:
    def homework(self, a, b):
        return [NS(id="1", subject=NS(name="Maths"), description="Contrôle secret de Lucie", date=date.today(), done=False, files=[])]
def fake_get_client():
    if state["mode"] == "auth": raise sync.TokenExpired("Connexion refusée : jeton expiré, régénérer le QR code")
    if state["mode"] == "error": raise ConnectionError("réseau coupé")
    return Client()
real_get_client = sync.get_client
sync.get_client = fake_get_client

with TestClient(app) as c:
    # migration du journal : les anciennes lignes sont classées d'après « ok »
    assert log()[:2] == [("ok", 1), ("error", 0)], log()

    # sans NOTIFY_URL : aucune notification, mais la bannière s'affiche quand même
    state["mode"] = "auth"; sync.run_sync()
    assert received == [] and log()[-1] == ("auth", 0)
    assert "refusé la connexion" in c.get("/").text and "data-reconnect" in c.get("/").text   # bannière + bouton de reconnexion

    # avec NOTIFY_URL : une notification à la perte du jeton, aucune tant que ça dure
    os.environ["NOTIFY_URL"] = URL; os.environ["NOTIFY_TOKEN"] = "tk_secret"
    state["mode"] = "ok"; sync.run_sync(); assert "refusé la connexion" not in c.get("/").text   # reconnecté
    n = len(received)                                      # (la reconnexion ci-dessus notifie « reconnecté »)
    assert received[-1]["title"] == "Devoirs Pronote : reconnecte", received[-1]
    state["mode"] = "auth"; sync.run_sync()
    assert len(received) == n + 1 and "expire" in received[-1]["title"]
    assert received[-1]["path"] == "/mon-topic" and received[-1]["auth"] == "Bearer tk_secret"
    assert "Lucie" not in received[-1]["body"] and "Contrôle" not in received[-1]["body"] and "Maths" not in received[-1]["body"]
    sync.run_sync(); sync.run_sync(); assert len(received) == n + 1, "pas de rappel à chaque synchro"
    assert "refusé la connexion" in c.get("/").text

    # retour à la normale : une seule notification « reconnecté », la bannière disparaît
    state["mode"] = "ok"; sync.run_sync()
    assert len(received) == n + 2 and received[-1]["title"].endswith("reconnecte")
    sync.run_sync(); assert len(received) == n + 2

    # une erreur ordinaire (réseau…) n'est ni une alerte jeton ni une notification
    state["mode"] = "error"; sync.run_sync()
    assert log()[-1] == ("error", 0) and len(received) == n + 2 and "refusé la connexion" not in c.get("/").text

    # notification impossible à envoyer : la synchro n'est pas bloquée, l'échec est journalisé
    os.environ["NOTIFY_URL"] = "http://127.0.0.1:1/injoignable"
    state["mode"] = "auth"; sync.run_sync()
    with db.conn() as x: last = x.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
    assert last["kind"] == "auth" and "notification non envoyée" in last["message"], dict(last)
    os.environ["NOTIFY_URL"] = URL

    # vraie get_client : sans credentials.json, ou jeton refusé par Pronote -> TokenExpired (donc bannière, pas « erreur »)
    sync.get_client = real_get_client
    for f in ("credentials.json",):
        if os.path.exists(sync.creds_path()): os.remove(sync.creds_path())
    try: sync.get_client(); raise SystemExit("get_client aurait dû échouer sans credentials.json")
    except sync.TokenExpired as e: assert "credentials.json" in str(e)
    with open(sync.creds_path(), "w") as f: json.dump({"pronote_url": "https://x/pronote/mobile.parent.html", "username": "u", "password": "p", "uuid": "z"}, f)
    class Refuse:
        @staticmethod
        def token_login(**kw): return NS(logged_in=False)
    sync.client_class = lambda url: Refuse
    try: sync.get_client(); raise SystemExit("get_client aurait dû échouer avec un jeton refusé")
    except sync.TokenExpired as e: assert "jeton expiré" in str(e)
    sync.run_sync()
    assert log()[-1] == ("auth", 0)
    print("OK")
