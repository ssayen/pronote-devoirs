"""Reconnexion à Pronote en déposant une capture du QR code (aucun réseau : le client Pronote est simulé)."""
import base64, io, json, os, sys, tempfile
from types import SimpleNamespace as NS

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["SYNC_INTERVAL_MIN"] = "0"
os.environ["APP_PASSWORD"] = "secret"            # l'endpoint doit être protégé comme le reste
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import zxingcpp
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from app import db, login, qr as qrmod, sync
from app.main import app

URL = "https://0831616f.index-education.net/pronote/mobile.parent.html"
GOOD = {"url": URL, "login": "login-secret", "jeton": "JETON-TRES-SECRET", "avecPageConnexion": False}

def qr_png(payload, *, screenshot=True) -> bytes:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    img = zxingcpp.write_barcode_to_image(zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode), scale=6)
    pil = Image.fromarray(img) if hasattr(Image, "fromarray") and not isinstance(img, Image.Image) else img
    pil = Image.frombytes("L", (img.width, img.height), bytes(img)) if not isinstance(pil, Image.Image) else pil
    if screenshot:   # le QR code au milieu d'une capture d'écran : fond clair, texte autour
        canvas = Image.new("RGB", (1000, 800), "#f2f4f8"); d = ImageDraw.Draw(canvas)
        d.rectangle((0, 0, 1000, 60), fill="#3b5bdb"); d.text((20, 25), "Pronote - Application mobile", fill="white")
        canvas.paste(pil.convert("RGB"), (320, 180)); pil = canvas
    out = io.BytesIO(); pil.save(out, "PNG"); return out.getvalue()
b64 = lambda raw: base64.b64encode(raw).decode()

attempts = []
class Fake:
    """Client Pronote simulé : accepte le PIN 0302."""
    @staticmethod
    def qrcode_login(qr, pin, uuid, **kw):
        attempts.append((qr["login"], pin))
        if pin != "0302": raise RuntimeError("PIN incorrect, jeton=" + qr["jeton"])   # le détail ne doit jamais fuiter
        return NS(logged_in=True, info=NS(name="M. Parent"),
                  export_credentials=lambda: {"pronote_url": qr["url"], "username": "u", "password": "NOUVEAU-JETON", "uuid": uuid})
qrmod.client_class = lambda url: Fake

synced = []
class Client:
    def homework(self, a, b): return []
sync.get_client = lambda: (synced.append(1), Client())[1]
AUTH = ("admin", "secret")

with TestClient(app) as c:
    post = lambda body, **kw: c.post("/api/reconnect", json=body, auth=AUTH, **kw)

    # protégé comme le reste de l'application
    assert c.post("/api/reconnect", json={"image": b64(qr_png(GOOD)), "pin": "0302"}).status_code == 401
    assert attempts == []

    # --- cas nominal : capture d'écran + bon PIN ---
    r = post({"image": b64(qr_png(GOOD)), "pin": "0302"})
    assert r.status_code == 200 and r.json() == {"ok": True, "name": "M. Parent"}, r.text
    assert attempts == [("login-secret", "0302")]
    creds = json.load(open(sync.creds_path())); assert creds["password"] == "NOUVEAU-JETON"
    assert synced, "une synchro doit suivre la reconnexion"
    # préfixe « data:image/png;base64, » accepté (c'est ce que produit le navigateur) ; QR seul, sans décor
    r = post({"image": "data:image/png;base64," + b64(qr_png(GOOD, screenshot=False)), "pin": "0302"}); assert r.status_code == 200, r.text

    # --- refus : jamais de fuite du jeton dans la réponse, et rien n'est écrit ---
    before = open(sync.creds_path()).read()
    def refused(body, code=400, needle=None):
        r = post(body); assert r.status_code == code, (r.status_code, r.text)
        for secret in ("JETON-TRES-SECRET", "login-secret", "NOUVEAU-JETON"): assert secret not in r.text, "fuite du jeton"
        if needle: assert needle in r.text, r.text
        assert open(sync.creds_path()).read() == before, "credentials.json ne doit pas changer"
    good = b64(qr_png(GOOD))
    refused({"image": good, "pin": "9999"}, needle="Connexion refusée")          # mauvais PIN / QR expiré
    refused({"image": good, "pin": "12"}, needle="4 chiffres")
    refused({"image": good, "pin": "abcd"}, needle="4 chiffres")
    refused({"image": b64(b"ceci n'est pas une image"), "pin": "0302"}, needle="illisible")
    refused({"image": "%%%pas-du-base64%%%", "pin": "0302"}, needle="illisible")
    blank = io.BytesIO(); Image.new("RGB", (400, 400), "white").save(blank, "PNG")
    refused({"image": b64(blank.getvalue()), "pin": "0302"}, needle="Aucun QR code")
    refused({"image": b64(qr_png("pas du json")), "pin": "0302"}, needle="Aucun QR code")
    refused({"image": b64(qr_png({"url": URL})), "pin": "0302"}, needle="pas un QR code Pronote")
    refused({"image": b64(qr_png({**GOOD, "url": "http://0831616f.index-education.net/x"})), "pin": "0302"}, needle="HTTPS")
    for bad in ("https://localhost/pronote/mobile.parent.html", "https://127.0.0.1/p", "https://10.0.0.5/p",
                "https://192.168.1.10/p", "https://169.254.169.254/latest", "https://[::1]/p", "https://svc.internal/p"):
        refused({"image": b64(qr_png({**GOOD, "url": bad})), "pin": "0302"}, needle="refusée")   # pas de SSRF
    refused({"image": b64(qr_png({**GOOD, "url": "https://autre-lycee.example.org/pronote/mobile.parent.html"})), "pin": "0302"},
            needle="autre serveur")                                              # un seul serveur Pronote
    refused({"image": b64(b"x" * (qrmod.MAX_IMAGE_BYTES + 1)), "pin": "0302"}, needle="trop volumineuse")
    assert len(attempts) == 3, attempts       # 2 réussies + 1 mauvais PIN : les cas invalides n'ont jamais contacté Pronote

    # --- désactivable (poste de dev : ne jamais parler à Pronote) ---
    os.environ["ALLOW_RECONNECT"] = "0"
    assert post({"image": good, "pin": "0302"}).status_code == 403 and len(attempts) == 3
    del os.environ["ALLOW_RECONNECT"]

    # --- une synchro en cours bloque la reconnexion le temps nécessaire (verrou partagé) ---
    sync.LOCK.acquire()
    try:
        orig = sync.LOCK.acquire
        class Busy:   # simule un verrou qui ne se libère pas dans les 30 s
            def acquire(self, timeout=None): return False
            def release(self): pass
        import app.main as m; real = m.sync.LOCK; m.sync.LOCK = Busy()
        assert post({"image": good, "pin": "0302"}).status_code == 409
        m.sync.LOCK = real
    finally: sync.LOCK.release()

    # --- la page propose le formulaire, et la bannière s'efface après une reconnexion ---
    page = c.get("/", auth=AUTH).text
    assert 'id="reconnect"' in page and "data-reconnect" in page and 'id="qr-pin"' in page

# --- ligne de commande : même logique, capture ou JSON ---
path = os.path.join(os.environ["DATA_DIR"], "capture.png"); open(path, "wb").write(qr_png(GOOD))
os.remove(sync.creds_path())
sys.argv = ["login", path, "0302"]; login.main(); assert os.path.exists(sync.creds_path())
os.remove(sync.creds_path())
sys.argv = ["login", json.dumps(GOOD), "0302"]; login.main(); assert os.path.exists(sync.creds_path())
sys.argv = ["login", path, "0000"]
try: login.main(); raise AssertionError("aurait dû échouer")
except SystemExit as e: assert "Connexion refusée" in str(e.code) and "JETON" not in str(e.code)
print("OK")
